# GeoLite2-City-CN

针对中国优化的 GeoLite2-City 数据库（MaxMind-DB City 格式）。以官方
GeoLite2-City 为基线，叠加纯真 qqwry 的中国大陆 IPv4 城市数据，
再叠加一层 IPv6 覆盖（GeoCN 为主、qqwry.ipdb 补省）。

- 中国大陆 IPv4：城市级覆盖，实测 60/60（100%），原 GeoLite2 仅 3.3%
- 家宽 IPv6：省覆盖 94%、市覆盖 33%
- 海外与官方 GeoLite2-City 一致（除 2 个经 RIR 数据证实为 GeoLite2
  标错国家的网段）

非官方增强版，与 MaxMind 没有隶属或背书关系；使用时须按 GeoLite2
许可署名 MaxMind。

## 部署

1. 下载 Release 里的 `GeoLite2-City-CN.mmdb`（61.8 MB，SHA256 见
   `SHA256SUMS`）。
2. 把软件里 GeoLite2-City.mmdb 的路径改成这个文件，重启服务。不
   用改源码。

任何能读 MaxMind City 格式的软件都能用（umami、nginx geoip2 等）。

## 字段

常用字段：`country` 是 `country.iso_code`（大陆为
`CN`）；`region` 是 `subdivisions[0].iso_code`，不带国家前缀
（广东 `GD`、北京 `BJ`）；`city` 是 `city.names.en`（英文/拼音；
中文名在 `names.zh-CN` 里备用）。`database_type` 是
`GeoLite2-City-CN`，`ip_version` 是 6（含 IPv4 映射
`::ffff:0:0/96`，IPv4 查询正常）。

## 本地构建

```bash
./build/build.sh
```

要求：Go ≥ 1.24、Python 3.12 + pypinyin、curl；验证另需 Node ≥ 20。
约 12 分钟、约 2 GB 内存。脚本自行下载全部源数据（带 SHA256
校验），不需要凭证和服务器访问。`Dockerfile` 也在 `build/` 里
（未在本地实测）。

## 自动更新（GitHub Actions）

`.github/workflows/build.yml`：每月 1 日 03:00 UTC 自动跑 `build.sh`，
成品（mmdb、conflicts.csv、README、SHA256SUMS）发为带日期标签的
Release。改构建脚本后推送到 main 会先跑一次构建验证（只传
Artifact，不发版）；也可以在 Actions 页手动触发。

仓库是私有的：纯真社区版数据限个人非商业用途，成品不公开发布。

## 数据来源

| 数据 | 用途 | 更新 |
|---|---|---|
| GeoLite2-City | 全量基线 | 每周 |
| qqwry.dat（metowolf，每周从纯真 CZDB 转制） | 大陆 IPv4 省 + 市 | 每周 |
| GeoCN.mmdb | IPv6 主源：区划码到市 | 2026-04-18 后未更新 |
| qqwry.ipdb（metowolf） | IPv6 补省 | 每周 |
| DB-IP Lite City | 只取经纬度，不取城市归属 | 每月 |
| APNIC 分配数据 | RIR 守卫：只叠加分配给 CN 的网段 | 每次构建 |

各文件 SHA256 见 `build/SOURCES.sha256`。纯真官方 2024-10 停了
.dat 格式，改用 metowolf 的转制版；GeoCN 自 2026-04-18 起未更新。

## 合并规则（要点）

- 基线是完整 GeoLite2-City，只叠加纯真的大陆记录；港澳台永远留在
  GeoLite2 一侧。
- 两边城市不一致 → 纯真胜出，记入 `conflicts.csv`（35,781 行）。
- 纯真只有省 → 只写国家 + 省，城市留空，不回填 GeoLite2 的旧城市；
  这些访客只显示到省。
- IPv6 只补空缺：GeoLite2 已有省或市的网段一律不动；GeoCN 为主、
  ipdb 补省。
- RIR 守卫：只叠加 APNIC 登记为 CN 的网段，拦住纯真把外国地址标
  成中国的记录（约 500 条）。
- 城市英文优先用 GeoLite2 已有拼写，没有的用无声调拼音；直辖市
  代码 BJ/SH/TJ/CQ。

## 文件

- `GeoLite2-City-CN.mmdb` / `conflicts.csv` / `SHA256SUMS` — 成品
  （Release 附件，不进 git）
- `build/` — 构建脚本（`build.sh`、`Dockerfile`、`merge_qqwry.py`、
  `merge_ipv6.py`、`dbip_coords.py`、`cmd/*`、`SOURCES.sha256`、
  `prefecture_cities.json`、`division_cities.json`）
- `work/` — 验证脚本与样本
