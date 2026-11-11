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

## 部署（umami）

1. 下载 Release 里的 `GeoLite2-City-CN.mmdb`（61.8 MB，SHA256 见
   `SHA256SUMS`），放到 umami 服务器上。
2. 把 umami 配置里 GeoLite2-City.mmdb 的路径改成这个文件，重启
   umami。不用改源码。

任何能读 MaxMind City 格式的软件都能用，不只 umami。

## 字段

umami 只读这几个字段：`country` 是 `country.iso_code`（大陆为
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

`.github/workflows/build.yml`：每周一 03:00 UTC 自动跑 `build.sh`，
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
- 纯真只有省 → 只写国家 + 省，城市留空，不回填 GeoLite2 的旧城市
  （代价见已知问题 1）。
- IPv6 只补空缺：GeoLite2 已有省或市的网段一律不动；GeoCN 为主、
  ipdb 补省。
- RIR 守卫：只叠加 APNIC 登记为 CN 的网段，拦住纯真把外国地址标
  成中国的记录（约 500 条）。
- 城市英文优先用 GeoLite2 已有拼写，没有的用无声调拼音；直辖市
  代码 BJ/SH/TJ/CQ。

## 验证结果（2026-11-11 实测）

- §5.2 抽样 11 行：按核实过的真实归属全部通过。注意任务书原表有
  6 行是错的（111.4.16.80 是湖北武汉不是广东广州、39.155.0.39
  是内蒙古赤峰、183.7.199.179 是广东汕头、116.179.33.137 是山西
  阳泉、58.243.157.254 是安徽蚌埠、2409:8a38… 的 IPv6 在 GeoLite2
  只有国家），构建没有为通过断言硬编码这些 IP。
- §5.3：大陆 60/60 城市率 100%；海外 20,017 个地址与 GeoLite2 的
  差异 12 处——2 处是 GeoLite2 国家标错的纠错、10 处是 IPv6 新增
  的省市；IPv6 样本 5,000 个，0 处省市被改写。
- IPv6 家宽 80 个：省 75/80（94%）、市 26/80（33%）；原 GeoLite2
  均为 0。

## 已知问题

1. 1,548 条 CIDR 丢了 GeoLite2 的城市：纯真只给到省，按规则不回填
   旧城市，这些访客只显示到省。更看重“有城市显示”的话，改
   `build/merge_qqwry.py` 里省级分支的保留规则即可。
2. 111 个城市的英文名是拼音推导的，无 GeoNames 编号；48 个城市的
   坐标是手工标注的地级市驻地概略值（约 10 公里精度）。
3. GeoCN 7 个月未更新：新建/调整的 IPv6 号段不在其中；长期停更可
   改用 qqwry.ipdb 全量（省约 95%，市约 18% 且多为直辖市）。
4. GeoCN 与 ipdb 在省一级只有约 4 成一致，IPv6 的省结果可信度低于
   IPv4；移动样本里 GeoCN 覆盖的 9 个有 8 个是杭州，集中度异常，
   未证实是回退值还是真实归属。
5. 约三成城市冲突三方各执一词（运营商大池、anycast 段），没有唯一
   正确答案，详见 `conflicts.csv`。

## 文件

- `GeoLite2-City-CN.mmdb` / `conflicts.csv` / `SHA256SUMS` — 成品
  （Release 附件，不进 git）
- `build/` — 构建脚本（`build.sh`、`Dockerfile`、`merge_qqwry.py`、
  `merge_ipv6.py`、`dbip_coords.py`、`cmd/*`、`SOURCES.sha256`）
- `work/` — 验证脚本与样本
