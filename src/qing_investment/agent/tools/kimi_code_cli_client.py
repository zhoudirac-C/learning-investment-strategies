"""Kimi Code CLI 本地调用客户端。

通过子进程执行 `kimi -p <prompt> --output-format text` 获取回答，
并对输出做清洗，使其适配 LangChain 的 `.invoke(prompt).content` 用法。

设计原则：
- 优先本地、失败/超时即抛异常，由上层决定是否 fallback；
- 输出清洗采用保守启发式：默认取最后一个 bullet（•）内容，
  因为 Kimi Code CLI 的内部思考通常在前面的 bullet，正式回答多在最后一条。
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

# 默认配置
_DEFAULT_CLI_PATH = "/home/ubuntu/.kimi-code/bin/kimi"
_DEFAULT_CWD = "/home/ubuntu/learning-investment-strategies"
# 从 300s 降到 120s： Qing-Agent 完整流程有多个 LLM 调用节点，单节点不能占用过长时间，
# 否则 hermes cron 客户端 900s timeout 仍会被打满导致 fallback。
_DEFAULT_TIMEOUT = 120


class KimiCodeCLIResponse:
    """模拟 ChatOpenAI.invoke() 的返回值结构，方便上层统一处理。"""

    def __init__(self, content: str):
        self.content = content

    def __repr__(self) -> str:
        return f"KimiCodeCLIResponse(content_len={len(self.content)})"


class KimiCodeCLIClient:
    """对 Kimi Code CLI 的极简封装。

    用法与 ChatOpenAI 大致兼容：
        client = KimiCodeCLIClient()
        resp = client.invoke("prompt text")
        print(resp.content)
    """

    def __init__(
        self,
        cli_path: str | None = None,
        cwd: str | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
        output_format: str = "text",
    ):
        self.cli_path = cli_path or os.environ.get("KIMI_CODE_CLI_PATH") or _DEFAULT_CLI_PATH
        self.cwd = cwd or os.environ.get("KIMI_CODE_CLI_CWD") or _DEFAULT_CWD
        self.timeout = timeout
        self.output_format = output_format

        # 验证 CLI 存在
        resolved = shutil.which(self.cli_path)
        if not resolved:
            raise KimiCodeCLIError(f"Kimi Code CLI not found: {self.cli_path}")
        self.cli_path = resolved

    # ── 公开方法 ──

    def stop(self) -> None:
        """No-op: the CLI client creates a one-shot subprocess per invoke()."""

    def invoke(self, prompt: str, **kwargs: Any) -> KimiCodeCLIResponse:
        """发一条 prompt，返回清洗后的 text 响应。

        Args:
            prompt: 用户消息文本。
            **kwargs: 额外参数（目前未使用，保留兼容性）。

        Returns:
            KimiCodeCLIResponse，具 .content 属性。

        Raises:
            KimiCodeCLIError: CLI 不存在、超时、非零退出码或输出为空。
        """
        logger.info(
            "[KimiCodeCLIClient] invoke: prompt_len=%d timeout=%d cwd=%s",
            len(prompt), self.timeout, self.cwd,
        )

        raw = self._run(prompt)
        cleaned = self._clean_output(raw)

        logger.info(
            "[KimiCodeCLIClient] invoke: raw_len=%d cleaned_len=%d",
            len(raw), len(cleaned),
        )

        # 清洗结果异常短时，把原始输出打到 warning 便于排查
        if len(cleaned) < 50:
            logger.warning(
                "[KimiCodeCLIClient] suspiciously short output: cleaned_len=%d raw_len=%d raw=%r",
                len(cleaned), len(raw), raw[:2000],
            )

        if not cleaned:
            raise KimiCodeCLIError("Kimi Code CLI returned empty output after cleaning")

        return KimiCodeCLIResponse(content=cleaned)

    # ── 内部方法 ──

    def _run(self, prompt: str) -> str:
        """执行子进程并返回原始 stdout。"""
        cmd = [
            self.cli_path,
            "-p", prompt,
            "--output-format", self.output_format,
        ]

        logger.debug("[KimiCodeCLIClient] run: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env={**os.environ, "TERM": "dumb"},
            )
        except subprocess.TimeoutExpired as e:
            raise KimiCodeCLIError(
                f"Kimi Code CLI timeout after {self.timeout}s"
            ) from e
        except FileNotFoundError as e:
            raise KimiCodeCLIError(
                f"Kimi Code CLI not found: {self.cli_path}"
            ) from e

        if result.returncode != 0:
            err = (result.stderr or result.stdout)[:800]
            raise KimiCodeCLIError(
                f"Kimi Code CLI exited with code {result.returncode}: {err}"
            )

        return result.stdout

    def _clean_output(self, text: str) -> str:
        """清洗 CLI 输出。

        策略（按优先级）：
        1. 去掉 ANSI 转义序列和 resume session 提示；
        2. 尝试提取 JSON 对象/数组（qing-agent 大量 prompt 要求返回 JSON）；
        3. 若存在 bullet（•）行，取连续 trailing bullets 的内容；
        4. 否则返回整体去空行后的文本。

        说明：Kimi Code CLI 的 stdout 通常只包含最终 bullet 回答，stderr 包含
        思考过程。但实际观察发现 stdout 也可能出现多条 bullet（思考+回答），
        因此这里优先 JSON 提取，再回退到 bullet 启发式。
        """
        import json

        # 1. 去掉 ANSI 转义序列
        text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)

        lines = text.splitlines()

        # 2. 去掉 resume session 提示
        lines = [
            ln for ln in lines
            if not ln.strip().startswith("To resume this session:")
        ]

        # 3. 去掉尾部空行
        while lines and not lines[-1].strip():
            lines.pop()

        # 4. 尝试提取 JSON
        joined = "\n".join(lines)
        json_candidate = self._extract_json(joined)
        if json_candidate:
            logger.debug(
                "[KimiCodeCLIClient] cleaned via JSON extraction, len=%d",
                len(json_candidate),
            )
            return json_candidate

        # 5. bullet 启发式：提取所有 bullet（•）块
        # 说明：Kimi Code CLI 的 stdout 里，最终回答通常放在 bullet 中；
        # 一个 bullet 可能跨多行（后续行缩进），多个 bullet 时也可能分段输出。
        # 思考过程一般走 stderr，不会混进来。
        bullet_blocks = self._extract_bullet_blocks(lines)
        if bullet_blocks:
            return "\n\n".join(bullet_blocks).strip()

        # 6. 无 bullet 时整体返回
        return "\n".join(ln.strip() for ln in lines if ln.strip()).strip()

    @staticmethod
    def _extract_bullet_blocks(lines: list[str]) -> list[str]:
        """从行列表中提取所有 bullet（•）块的内容。

        每个 bullet 块从 `• ` 开始，后续缩进行或空行都属于同一块，
        直到遇到下一个 `• ` 或非缩进的非空行。
        """
        blocks: list[str] = []
        current: list[str] = []
        base_indent: int | None = None

        for ln in lines:
            stripped = ln.lstrip()
            if stripped.startswith("• "):
                # 新 bullet，先结束当前块
                if current:
                    blocks.append(KimiCodeCLIClient._dedent_block(current))
                current = [stripped[2:]]
                base_indent = None
                continue

            if current:
                # 空行或缩进行属于当前 bullet 的延续
                if not stripped:
                    current.append("")
                    continue

                # 计算当前行缩进
                indent = len(ln) - len(ln.lstrip())
                if base_indent is None and indent > 0:
                    base_indent = indent

                # 如果缩进小于 base_indent 且不是空行，认为块结束
                if base_indent is not None and indent < base_indent:
                    blocks.append(KimiCodeCLIClient._dedent_block(current))
                    current = []
                    base_indent = None
                else:
                    current.append(ln)

        if current:
            blocks.append(KimiCodeCLIClient._dedent_block(current))

        return blocks

    @staticmethod
    def _dedent_block(lines: list[str]) -> str:
        """去掉 bullet 块内续行的公共缩进。"""
        # 过滤掉尾部空行
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            return ""

        # 第一行已经是去掉 `• ` 的内容，没有缩进
        # 续行的公共缩进是第一行之后所有非空行的最小缩进
        indents = [
            len(ln) - len(ln.lstrip())
            for ln in lines[1:]
            if ln.strip()
        ]
        min_indent = min(indents) if indents else 0

        result = [lines[0]]
        for ln in lines[1:]:
            if ln.strip():
                # 去掉公共缩进，但保留相对缩进
                if len(ln) >= min_indent:
                    ln = ln[min_indent:]
            result.append(ln.rstrip())

        return "\n".join(result).strip()

    @staticmethod
    def _extract_json(text: str) -> str | None:
        """从文本中提取第一个合法的 JSON 对象或数组字符串。"""
        import json

        # 策略 A：直接尝试整个文本
        stripped = text.strip()
        for candidate in (stripped, stripped.strip("`").lstrip("json").strip()):
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                pass

        # 策略 B：找 {} 或 [] 包围的最长合法子串
        for start_char, end_char in (("{", "}"), ("[", "]")):
            start = text.find(start_char)
            if start == -1:
                continue
            # 从第一个 start_char 开始，逐步往后试
            for end in range(len(text), start, -1):
                if text[end - 1] != end_char:
                    continue
                candidate = text[start:end]
                try:
                    parsed = json.loads(candidate)
                    # 忽略空对象/数组：markdown 中常出现占位符 {}，
                    # 提取它们会覆盖真正的文本内容（如 style_writer 的 markdown）。
                    if isinstance(parsed, dict) and not parsed:
                        continue
                    if isinstance(parsed, list) and not parsed:
                        continue
                    return candidate
                except json.JSONDecodeError:
                    continue

        return None


class KimiCodeCLIError(Exception):
    """Kimi Code CLI 调用异常。"""

    def __init__(self, message: str):
        super().__init__(message)
