---
source: "bilibili_dynamic"
up_uid: "1420210197"
up_name: "青枫浦上Q"
dynamic_id: "1264952286306631720"
dynamic_type: "图片"
pub_time: "2026年10月30日 19:00"
fetch_time: "2026-10-30T21:00:15.117945"
url: "https://www.bilibili.com/opus/1264952286306631720"
pics_count: 0
like: 31
comment: 102
forward: 0
is_only_fans: true
unprocessed: true
---

> 来源：B站动态 [青枫浦上Q](https://space.bilibili.com/1420210197)
> 发布时间：2026年10月30日 19:00
> 动态链接：https://www.bilibili.com/opus/1264952286306631720

## 原文

1，Lucas sequence
GG:(CLOSE-REF(CLOSE,29))/REF(CLOSE,29),COLORWHITE;
JGTP1:MA(GG,29),COLORYELLOW;
JGTP2:MA(GG,47),COLORMAGENTA; 


2，Boll终极版
N:=29;
SD:=STD(CLOSE,N);

BOLL:MA(CLOSE,N),COLOR808080,DOTLINE;
顶轨:BOLL+3*SD,COLOR808080,DOTLINE;
一轨:BOLL+2*SD,COLOR808080,DOTLINE;
二轨:BOLL+SD,COLORYELLOW,DOTLINE;
四轨:BOLL-SD,COLORRED,DOTLINE;
五轨:BOLL-2*SD,COLOR808080,DOTLINE;
底轨:BOLL-3*SD,COLOR808080,DOTLINE;

STICKLINE(1,HIGH,LOW,0,0),COLORGREEN;
STICKLINE(1,OPEN,CLOSE,2,0),COLORGREEN;

STICKLINE(LOW<底轨 AND CLOSE>底轨,LOW,底轨,0,0),COLORWHITE;

YELLOWBAR:=LOW>四轨;
STICKLINE(YELLOWBAR,HIGH,LOW,0,0),COLORYELLOW;
STICKLINE(YELLOWBAR,OPEN,CLOSE,2,0),COLORYELLOW;

RIN:=CLOSE>一轨;
ROUT:=CLOSE<二轨;
REDBAR:=COUNT(RIN,0)>0 AND
       (COUNT(ROUT,0)=0 OR BARSLAST(RIN)<BARSLAST(ROUT));
STICKLINE(REDBAR,HIGH,LOW,0,0),COLORRED;
STICKLINE(REDBAR,OPEN,CLOSE,2,0),COLORRED;

PURPLEBAR:=CLOSE>顶轨;
STICKLINE(PURPLEBAR,HIGH,LOW,0,0),COLORMAGENTA;
STICKLINE(PURPLEBAR,OPEN,CLOSE,2,0),COLORMAGENTA;

STICKLINE(HIGH>顶轨,HIGH,顶轨,0,0),COLORMAGENTA; 

3. KDJ终极版
NN:=5;
TT:=2;
RNG:=HHV(HIGH,NN)-LLV(LOW,NN);
RSV:=IF(RNG=0,50,(CLOSE-LLV(LOW,NN))/IF(RNG=0,1,RNG)*100);
KV:=SMA(RSV,2,1);
DV:=SMA(KV,2,1);
JV:=3*DV-2*KV;
GAP:=KV-DV;
TOP3:=MAX(MAX(KV,DV),JV);
BOT3:=MIN(MIN(KV,DV),JV);

HZ:=MIN(KV,DV)>80;
LZ:=MAX(KV,DV)<20;
NH:=BARSCOUNT(CLOSE)>5 AND HIGH>REF(HHV(HIGH,5),1);
NL:=BARSCOUNT(CLOSE)>5 AND LOW<REF(LLV(LOW,5),1);
HENT:=HZ AND COUNT(HZ,3)>=2 AND COUNT(NH,3)>0;
LENT:=LZ AND COUNT(LZ,3)>=2 AND COUNT(NL,3)>0;

HRESET:=DV<70 OR BARSCOUNT(CLOSE)=1;
LRESET:=DV>30 OR BARSCOUNT(CLOSE)=1;
HSTATE:=COUNT(HENT,0)>0 AND BARSLAST(HENT)<BARSLAST(HRESET);
LSTATE:=COUNT(LENT,0)>0 AND BARSLAST(LENT)<BARSLAST(LRESET);

HTIGHT:=HSTATE AND BOT3>80 AND ABS(GAP)<2;
LTIGHT:=LSTATE AND TOP3<20 AND ABS(GAP)<2;

STICKLINE(HSTATE,80,100,4,0),COLOR222266;
STICKLINE(LSTATE,0,20,4,0),COLOR664422;
STICKLINE(HTIGHT,96,100,3,0),COLORYELLOW;
STICKLINE(LTIGHT,0,4,3,0),COLORYELLOW;

K:KV,COLORWHITE;
D:DV,COLORYELLOW;
J:JV,COLORRED;
20,COLORGREEN;
50,COLORWHITE;
80,COLORRED;

DRAWTEXT(HSTATE AND REF(HSTATE,1)=0,103,'高位滞留'),COLORRED;
DRAWTEXT(LSTATE AND REF(LSTATE,1)=0,-6,'低位滞留'),COLORCYAN;

LZONE:=LLV(TOP3,3)<20;
HZONE:=HHV(BOT3,3)>80;
UP0:=LZONE AND GAP>TT AND CLOSE>REF(CLOSE,1);
DN0:=HZONE AND GAP<0-TT AND CLOSE<REF(CLOSE,1);
UPSIG:=UP0 AND REF(UP0,1)=0;
DNSIG:=DN0 AND REF(DN0,1)=0;
DRAWTEXT(UPSIG AND LSTATE,KV+8,'低位反抽'),COLORCYAN;
DRAWTEXT(UPSIG AND LSTATE=0,KV-8,'转强'),COLORMAGENTA;
DRAWTEXT(DNSIG AND HSTATE,KV-8,'高位回落'),COLORRED;
DRAWTEXT(DNSIG AND HSTATE=0,KV+8,'转弱'),COLORGREEN;

DRAWTEXT(REF(LSTATE,1) AND LSTATE=0,32,'低区解除'),COLORYELLOW;
DRAWTEXT(REF(HSTATE,1) AND HSTATE=0,68,'高区解除'),COLORYELLOW;

## 置顶评论

> 👤 **青枫浦上Q**
> 👍 26
>
> 自己用，别发到网上去。 这是通达信的，你想用别的版本，让豆包给你改一下就行。

## 图片

> 充电专属动态，图片需访问原页面查看。
> 链接：https://www.bilibili.com/opus/1264952286306631720

## 互动数据

- 点赞：31
- 评论：102
- 转发：0

<!--
## 原始API数据

```json
{
  "id_str": "1264952286306631720",
  "type": "DYNAMIC_TYPE_DRAW",
  "basic": {
    "rid_str": "413820512",
    "comment_type": 11,
    "comment_id_str": "413820512",
    "like_icon": {
      "id": "0",
      "start_url": "",
      "action_url": "",
      "end_url": ""
    },
    "in_audit": false,
    "is_only_fans": true,
    "editable": false,
    "open_app_extra": "",
    "jump_url": "",
    "aigc": false
  },
  "visible": true,
  "modules": {
    "module_tag": null,
    "module_author": {
      "type": "AUTHOR_TYPE_NORMAL",
      "avatar": {
        "container_size": {
          "width": 1.35,
          "height": 1.35
        },
        "layers": [],
        "fallback_layers": {
          "group_id": "",
          "layers": [
            {
              "layer_id": "",
              "visible": true,
              "general_spec": {
                "pos_spec": {
                  "coordinate_pos": 2,
                  "axis_x": 0.675,
                  "axis_y": 0.675
                },
                "size_spec": {
                  "width": 1,
                  "height": 1
                },
                "render_spec": {
                  "opacity": 1
                }
              },
              "layer_config": {
                "tags": {
                  "AVATAR_LAYER": {
                    "config_type": 0
                  },
                  "GENERAL_CFG": {
                    "config_type": 1,
                    "general_config": {
                      "web_css_style": {
                        "borderRadius": "50%"
                      }
                    }
                  }
                },
                "is_critical": true,
                "allow_over_paint": false,
                "layer_mask": null
              },
              "resource": {
                "res_type": 3,
                "res_image": {
                  "image_src": {
                    "src_type": 1,
                    "placeholder": 6,
                    "remote": {
                      "url": "https://i0.hdslb.com/bfs/face/b99dd748cf6e4152626952fb238f7ab44691658e.jpg",
                      "bfs_style": "widget-layer-avatar"
                    }
                  }
                }
              }
            },
            {
              "layer_id": "",
              "visible": true,
              "general_spec": {
                "pos_spec": {
                  "coordinate_pos": 1,
                  "axis_x": 0.8000000000000002,
                  "axis_y": 0.8000000000000002
                },
                "size_spec": {
                  "width": 0.41666666666666663,
                  "height": 0.41666666666666663
                },
                "render_spec": {
                  "opacity": 1
                }
              },
              "layer_config": {
                "tags": {
                  "GENERAL_CFG": {
                    "config_type": 1,
                    "general_config": {
                      "web_css_style": {
                        "background-color": "rgb(255,255,255)",
                        "border": "2px solid rgba(255,255,255,1)",
                        "borderRadius": "50%",
                        "boxSizing": "border-box"
                      }
                    }
                  },
                  "ICON_LAYER": {
                    "config_type": 0
                  }
                },
                "is_critical": false,
                "allow_over_paint": false,
                "layer_mask": null
              },
              "resource": {
                "res_type": 3,
                "res_image": {
                  "image_src": {
                    "src_type": 2,
                    "placeholder": 0,
                    "local": 1
                  }
                }
              }
            }
          ],
          "group_mask": null,
          "is_critical_group": true
        },
        "mid": "1420210197"
      },
      "face": "https://i0.hdslb.com/bfs/face/b99dd748cf6e4152626952fb238f7ab44691658e.jpg",
      "face_nft": false,
      "nft_info": null,
      "name": "青枫浦上Q",
      "name_render": null,
      "label": "",
      "mid": 1420210197,
      "jump_url": "//space.bilibili.com/1420210197/dynamic",
      "following": true,
      "pub_ts": "1793358055",
      "pub_time": "2026年10月30日 19:00",
      "pub_action": "",
      "pub_location_text": "",
      "pendant": {
        "pid": 0,
        "name": "",
        "image": "",
        "expire": "0",
        "image_enhance": "",
        "image_enhance_frame": "",
        "n_pid": "0"
      },
      "vip": {
        "type": 2,
        "status": 1,
        "due_date": "1823702400000",
        "vip_pay_type": 1,
        "theme_type": 0,
        "label": {
          "path": "http://i0.hdslb.com/bfs/vip/label_annual.png",
          "text": "年度大会员",
          "label_theme": "annual_vip",
          "text_color": "#FFFFFF",
          "bg_style": 1,
          "bg_color": "#FB7299",
          "border_color": "",
          "use_img_label": true,
          "img_label_uri_hans": "",
          "img_label_uri_hant": "",
          "img_label_uri_hans_static": "https://i0.hdslb.com/bfs/vip/8d4f8bfc713826a5412a0a27eaaac4d6b9ede1d9.png",
          "img_label_uri_hant_static": "https://i0.hdslb.com/bfs/activity-plat/static/20220614/e369244d0b14644f5e1a06431e22a4d5/VEW8fCC0hg.png"
        },
        "avatar_subscript": 1,
        "nickname_color": "#FB7299",
        "role": "3",
        "avatar_subscript_url": "",
        "tv_vip_status": 0,
        "tv_vip_pay_type": 0,
        "tv_due_date": "0",
        "avatar_icon": {
          "icon_type": 1,
          "icon_resource": {
            "type": 0,
            "url": ""
          }
        }
      },
      "official_verify": {
        "type": -1,
        "desc": ""
      },
      "decorate": null,
      "decoration_card": null,
      "is_top": false,
      "icon_badge": {
        "text": "充电专属",
        "icon": "https://i0.hdslb.com/bfs/garb/item/33e2e72d9a0c855f036b4cb55448f44af67a0635.png",
        "render_img": "https://i0.hdslb.com/bfs/activity-plat/static/20230112/3b3c5705bda98d50983f6f47df360fef/IN4E1b8HNg.png"
      },
      "views_text": "",
      "official": null,
      "more": null,
      "decorate_card": null,
      "identity_badges": []
    },
    "module_more": {
      "rcmd_text": "",
      "three_point_items": [
        {
          "label": "举报",
          "type": "THREE_POINT_REPORT",
          "params": {},
          "modal": null,
          "jump_url": ""
        }
      ]
    },
    "module_dispute": null,
    "module_dynamic": {
      "topic": null,
      "desc": null,
      "major": {
        "type": "MAJOR_TYPE_DRAW",
        "none": null,
        "blocked": null,
        "archive": null,
        "pgc": null,
        "courses": null,
        "draw": {
          "items": [],
          "id": "413820512"
        },
        "article": null,
        "music": null,
        "common": null,
        "upower_common": null,
        "live": null,
        "live_rcmd": null,
        "medialist": null,
        "subscription": null,
        "ugc_season": null,
        "subscription_new": null,
        "opus": null
      },
      "additional": null
    },
    "module_extend": null,
    "module_stat": {
      "forward": {
        "status": false,
        "count": 0,
        "forbidden": true,
        "disabled": true,
        "silent": false,
        "hidden": false
      },
      "comment": {
        "status": false,
        "count": 102,
        "forbidden": false,
        "disabled": false,
        "silent": false,
        "hidden": false
      },
      "like": {
        "status": false,
        "count": 31,
        "forbidden": false,
        "disabled": false,
        "silent": false,
        "hidden": false
      },
      "coin": null,
      "favorite": null
    },
    "module_interaction": null,
    "module_share_info": null,
    "module_fold": null
  },
  "orig": null
}
```
-->