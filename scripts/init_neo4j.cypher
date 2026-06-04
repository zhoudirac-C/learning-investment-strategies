// Neo4j 初始约束和索引
// 运行方式：在 Neo4j Browser 中执行，或通过 cypher-shell

// 创建唯一约束
CREATE CONSTRAINT claim_id IF NOT EXISTS
FOR (c:Claim) REQUIRE c.id IS UNIQUE;

CREATE CONSTRAINT stock_code IF NOT EXISTS
FOR (s:Stock) REQUIRE s.code IS UNIQUE;

CREATE CONSTRAINT sector_name IF NOT EXISTS
FOR (s:Sector) REQUIRE s.name IS UNIQUE;

CREATE CONSTRAINT wiki_path IF NOT EXISTS
FOR (w:WikiPage) REQUIRE w.path IS UNIQUE;

// 创建索引（加速查询）
CREATE INDEX claim_source_date IF NOT EXISTS
FOR (c:Claim) ON (c.source_date);

CREATE INDEX claim_status IF NOT EXISTS
FOR (c:Claim) ON (c.status);

CREATE INDEX claim_type IF NOT EXISTS
FOR (c:Claim) ON (c.claim_type);

CREATE INDEX claim_subject IF NOT EXISTS
FOR (c:Claim) ON (c.subject);

CREATE INDEX stock_name IF NOT EXISTS
FOR (s:Stock) ON (s.name);

// 打印完成信息
RETURN "Neo4j constraints and indexes created successfully" AS status;
