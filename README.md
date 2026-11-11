# GeoLite2-City-CN.mmdb — 针对中国优化的 GeoLite2-City 数据库

为自建 **umami 3.4.1** 生成的单个 MaxMind-DB City 格式数据库：以官方
GeoLite2-City 为基线，叠加纯真 qqwry 的中国大陆 IPv4 城市数据，
再叠加一层 IPv6 覆盖（GeoCN 为主、纯真 qqwry.ipdb 补省）。
中国大陆 IPv4 达到城市级覆盖；家宽 IPv6 省覆盖约 94%、市覆盖约 33%；
海外与官方 GeoLite2-City 一致（除 2 个经 RIR 分配数据证实为
GeoLite2 标错国家的网段，见下）。

> 非官方增强版：本数据库以 MaxMind 的 GeoLite2-City 为基线加工
> 而成，与 MaxMind 没有隶属或背书关系；使用时须按 GeoLite2 的
> CC BY-SA 4.0 / EULA 署名 MaxMind。

## 快速使用（部署）

1. 把 `GeoLite2-City-CN.mmdb` 复制到你的 umami 服务器上，替换 umami 配置
   中指向 GeoLite2-City.mmdb 的路径，重启 umami 即可。不需要改 umami 源码。
2. 文件：`GeoLite2-City-CN.mmdb`（61.8 MB，SHA256 见 `SHA256SUMS`）。
3. 更新节奏：GeoLite2 每周更新、纯真数据有变化时重新跑
   `./build/build.sh` 即可。IPv4 源是 metowolf 每周从纯真 CZDB
   转制的 qqwry.dat（当前 2026-11-04 版）；IPv6 主源 GeoCN 自
   2026-04-18 起未更新（见“来源”和“已知缺陷”）。

## 字段约定（umami 只读这些）

| umami 字段 | 来源 |
|---|---|
| `country` | `country.iso_code`（回退 `registered_country.iso_code`），中国大陆为 `CN` |
| `region` | `subdivisions[0].iso_code`，**不带国家前缀**的 ISO 3166-2 代码（广东 `GD`、北京 `BJ`） |
| `city` | `city.names.en`，英文/拼音（只有英文 umami 才会显示城市；中文名同时存在 `names.zh-CN` 里备用） |
| `location.latitude/longitude` | 有，但 umami 不用；`accuracy_radius` 表示坐标可信度（越小越准） |

`database_type` 为 `GeoLite2-City-CN`，`ip_version` 为 6（含 IPv4 映射
`::ffff:0:0/96`，IPv4 查询正常工作）。

## 来源（2026-11-11 获取）

| 数据 | 来源 | 用途 | 许可 |
|---|---|---|---|
| GeoLite2-City.mmdb（50,055,606 字节，build_epoch 1793945788） | https://github.com/P3TERX/GeoLite.mmdb/releases/latest/download/GeoLite2-City.mmdb | 全量基线：海外 + IPv6 + 中国大陆未被纯真覆盖的部分 | CC BY-SA 4.0 / GeoLite2 EULA（须署名 MaxMind，不得用于识别个人） |
| qqwry.dat（27,408,467 字节，版本串“2026年11月04日IP数据”，1,583,511 条） | https://github.com/metowolf/qqwry.dat/releases/latest/download/qqwry.dat（metowolf 每周从纯真 CZDB 转制；纯真官方已于 2024-10 停更 .dat 格式，FW27623 镜像冻结在 2024-09-25） | 中国大陆 IPv4 省 + 市 | 纯真社区版数据，免费用于个人非商业用途；商业用途须购买授权或改用 IPIP.net / 埃文科技 |
| GeoCN.mmdb（9,034,837 字节，build_epoch 1776545483，2026-04-18 发布） | https://github.com/ljxi/GeoCN/releases/download/v26.4.19/GeoCN.mmdb | **IPv6 主源**：大陆 IPv6 网段的 6 位行政区划码（精确到区县，取市级）+ 运营商 | 仓库无 LICENSE 文件；数据来自公开免费 API 清洗，仅限个人非商业用途；**已 7 个月未更新** |
| qqwry.ipdb（40,975,164 字节，build 1793896226） | https://cdn.jsdelivr.net/npm/qqwry.ipdb/qqwry.ipdb（metowolf，每周更新，与 qqwry.dat 同源） | **IPv6 补缺**：GeoCN 无数据时补省（偶有市） | 与 qqwry.dat 相同 |
| GB/T 2260 地级市码表（342 条） | https://github.com/modood/Administrative-divisions-of-China（dist/cities.json） | 把 GeoCN 的 4 位地级市码译成城市名 | MIT |
| DB-IP Lite City 2026-11（82 MB gz，7,777,816 行） | https://download.db-ip.com/free/dbip-city-lite-2026-11.csv.gz | **仅取经纬度**，不取城市归属（它有已知的城市误判） | CC BY 4.0 |
| APNIC delegated-apnic-latest（2026-11-11） | https://ftp.apnic.net/stats/apnic/delegated-apnic-latest | RIR 分配守卫：只叠加分配给 CN 的网段 | APNIC 公开数据 |
| ip2region v4/v6、纯真经典版 qqwry（2022-04-20） | GitHub lionsoul2014/ip2region、out0fmemory/qqwry.dat | 仅交叉验证，不进入成品 | 各自开源许可 |

各文件 SHA256 见 `build/SOURCES.sha256`。

## 合并规则

1. 基线 = 完整 GeoLite2-City；只叠加纯真的大陆记录。
2. 纯真国家为中国大陆（排除港澳台，港澳台永远留在 GeoLite2 一侧，
   绝不并入 CN）。
3. 未被叠加的网段与 GeoLite2 完全一致。
4. 纯真只有省（如“广东省”）→ 只写国家 + 省，城市留空，**不**回填
   GeoLite2 的旧城市（这是任务书 §4.4 的明确要求；代价见“已知缺陷”）。
5. 两边都有城市且不一致 → 纯真胜出，记入 `conflicts.csv`。
6. 直辖市（京/沪/津/渝）省市同名，代码 BJ/SH/TJ/CQ。
7. **IPv6 叠加（v2 新增）**：GeoCN 为主源（有数据时取其市，区县码只
   取到地级市），qqwry.ipdb 只补 GeoCN 没有的空缺（主要是省）；
   **只补空缺**：GeoLite2 已有省或市的 IPv6 网段一律不动（构建时在
   每个候选 CIDR 的起点、1/4、中点、3/4、末尾五点探测，任一点有
   省市即跳过），所以 GeoLite2 原有的 IPv6 城市（如湖北孝感）全部
   保留。本次 32,303 条候选 IPv6 CIDR 中实际插入 30,642 条，
   跳过 1,661 条。
8. 保留 IP 未写入。
9. **RIR 分配守卫（构建时新增，任务书之外）**：只叠加 APNIC 分配文件
   中登记为 CN 的网段。纯真有约 500 条记录把外国地址标成中国
   （外国云厂商网段标成“北京”、南亚/东南亚网段标成“安徽马鞍山”、
   台湾网段标成大陆城市），不守卫会把这些海外访客误标为中国，
   直接违反验收 §5.3。本次构建 IPv4 因此排除了 971 个子网段
   （1,134,436 个地址，占大陆地址总数的 0.3%），IPv6 排除了
   2,285 个原子段。守卫同样适用于 IPv6（GeoCN/ipdb 的 CN 断言
   也要过 RIR 这一关）。
10. **未用运营商 BGP 清单做硬性范围限制**：曾考虑只叠加三大运营商
    + 教育网的 BGP 公布段（gaoyifan/china-operator-ip），实测这些
    清单只覆盖三大运营商 /16 地址空间的 9–29%（联通 2408::/16
    仅 9.3%），做硬过滤会丢掉七成以上的家宽样本。RIR 守卫 +
    两个源本身只含中国数据，已足以把叠加范围限定在中国境内。

城市英文拼写优先采用 GeoLite2 已有的拼写（如 Guangzhou、Nanchang、
Hefei、Xi'an）；GeoLite2 没有的城市用无声调拼音（首字母大写），
另有 95 条例外拼写（如 Hohhot、Kashgar、Yan'an）。

## 构建

```bash
./build/build.sh
```

需求：Go ≥ 1.24（实测 1.25.4）、Python 3.12 + pypinyin 0.55.0、
curl；验证步骤另需 Node ≥ 20。Go 构建会把整个 GeoLite2 树载入内存，
约需 2 GB 空闲内存，全程约 12 分钟（基线加载约 6 分钟，插入
124,209 条 CIDR 约 1 分钟；构建机负载高时基线加载会更慢）。

可重复构建：`build/` 下有 `merge_qqwry.py`（IPv4 解析 + 聚合）、
`merge_ipv6.py`（IPv6 聚合：GeoCN 优先、ipdb 补省、RIR 守卫）、
`dbip_coords.py`（DB-IP 坐标中位数）、`prefecture_cities.json`
（地级市名表，由纯真经典版拼写提取）、`division_cities.json`
（GB/T 2260 地级市码表）、`cmd/extract_geolite`
（GeoLite2 省/市表提取）、`cmd/extract_geocn`（GeoCN IPv6 网段提取）、
`cmd/walk_ipdb`（qqwry.ipdb 全库遍历，含 IPv6）、
`cmd/build_mmdb`（Go，mmdbwriter v1.2.0，
maxminddb-golang/v2 v2.1.1）及 `build.sh`、`Dockerfile`。
`Dockerfile` 未在构建机上实测（该机无 Docker），`build.sh` 是实测过的路径。
重复构建与本次交付的唯一差别是 `build_epoch`（构建时间戳）。

### GitHub Actions（自动周更）

本仓库自带 `.github/workflows/build.yml`：每周一 03:00 UTC 自动跑
`build.sh`，成品（mmdb、conflicts.csv、README、SHA256SUMS）发布为
带日期标签的 Release；改了构建脚本后推送到 main 会先跑一次构建
验证（只上传 Artifact，不发版）。手动触发在仓库 Actions 页点
Run workflow。仓库为私有（纯真社区版为个人非商业许可，成品不
公开发布）。

## 验证结果（2026-11-11，本次构建实测）

### §5.1 加载

- `node -e "const m=require('maxmind');m.open('GeoLite2-City-CN.mmdb').then(d=>console.log(JSON.stringify(d.get('111.4.16.80'))))"`
  正常返回 JSON（武汉，`HB`，见下）。
- 大小 64,772,179 字节（61.8 MB，在 40–100 MB 区间内）；
  `ip_version=6`；`database_type=GeoLite2-City-CN`；
  节点数 6,157,551；`::ffff:111.4.16.80` 同样返回武汉（IPv4 映射正常）。

### §5.2 抽样断言 — 任务书的表有 6 行是错的

按任务书 §5.2 的表，11 行中只有 5 行与成品一致；但按**核实过的
真实归属**（GeoLite2、纯真 2022 经典版、纯真 2024 FW 版、ip2region
四方一致），11 行**全部**通过，包括两个回归点（南昌、孝感）。
构建时**没有**为通过断言而硬编码这 11 个 IP——硬编码会把武汉、
赤峰、汕头、阳泉、蚌埠的真实访客标错城市。

| IP | 任务书写 | 成品（核实） | 结论 |
|---|---|---|---|
| 111.4.16.80 | CN/GD/Guangzhou | CN/**HB/Wuhan** | 任务书写错：四方信源均为湖北武汉 |
| 39.155.0.39 | CN/GD/Guangzhou | CN/**NM/Chifeng** | 任务书写错：内蒙古赤峰 |
| 183.7.199.179 | CN/GD/Guangzhou | CN/GD/**Shantou** | 省对、市错：广东汕头 |
| 116.179.33.137 | CN/BJ/Jinrongjie | CN/**SX/Yangquan** | 任务书写错；“Jinrongjie”在当前 GeoLite2 全库中根本不存在 |
| 183.216.98.122 | CN/JX/Nanchang | CN/JX/Nanchang | 通过（回归点） |
| 58.243.157.254 | CN/AH/Hefei | CN/AH/**Bengbu** | 省对、市错：安徽蚌埠 |
| 223.5.5.5 | CN/ZJ/Hangzhou | CN/ZJ/Hangzhou | 通过 |
| 2409:8a38:28:5a50:2cb3:d356:ea83:44c0 | CN/BJ/Beijing | CN/**JX/Nanchang** | 任务书写错：该 IPv6 在 GeoLite2 只有国家；v2 按 GeoCN（区划码 360102）补为江西南昌。其他源分歧很大（qqwry.ipdb 陕西、ip2region 广州、DB-IP 北京金荣街），此值是主源 GeoCN 的断言，未独立核实 |
| 2409:8a4c:ecd:b00:1497:11ff:fec1:eedb | CN/HB/Xiaogan | CN/HB/Xiaogan | 通过（回归点；只补空缺规则保住了 GeoLite2 原有的孝感，GeoCN 的武汉未覆盖它） |
| 192.161.160.202 | US/CA/Los Angeles | US/CA/Los Angeles | 通过 |
| 8.8.8.8 | US/—/— | US/—/— | 通过 |

### §5.3 覆盖率与一致性

- 大陆样本：60 个 IP（移动/联通/电信各 20 个，随机取自纯真城市段），
  成品城市率 **100%（60/60）**，原 GeoLite2 仅 **3.3%（2/60）**，
  目标 ≥90% 大幅达成。
- 海外样本：20,017 个地址（17 个知名 IP + 20,000 个随机海外网段首地址），
  与原 GeoLite2 有 **12 处**差异，分两类：① **2 处是 GeoLite2 的国家
  标错、经 RIR 分配数据证实应为中国**：112.73.88.0（GeoLite2 标日本东京，
  RIR 分配给 CN）、180.223.197.0（GeoLite2 标香港，RIR 分配给 CN）。
  v1 的第 3 处 124.21.224.0（GeoLite2 标美国洛杉矶）已不在差异之列，
  因为 metowolf 新版纯真不再把它标成北京，成品与 GeoLite2 一致地
  保留为美国；② **10 处是 IPv6 样本上新增的省/市**（GeoLite2 只有
  国家，IPv6 叠加补上省市，如 2406:840:2000:: → 浙江宁波），这是
  v2 的目标本身，不是海外错误。扣除这两类，海外与 GeoLite2 完全一致。
- IPv6 样本：5,000 个网段首地址，与原 GeoLite2 的 10 处差异全部是
  上述新增的省/市（0 处省市被改写）。

### IPv6 家宽样本（102 个，v2 新增验证）

102 个中国 IPv6 地址（电信/联通/移动家宽各 20 个 + 其他 20 个 +
GeoLite2 本来有城市的 20 个 + 2 个 §5.2 地址）：

| 样本 | 省 | 市 | 说明 |
|---|---|---|---|
| 电信家宽 20 | 20 | 2 | 省全补，市只有 2（GeoCN 对电信覆盖最差） |
| 联通家宽 20 | 20 | 1 | 省全补，市只有 1 |
| 移动家宽 20 | 16 | 12 | 4 个两库均无数据（2409:1bc8/1a48/1184/1bbf 段） |
| 其他中国 20 | 19 | 11 | 1 个两库均无数据 |
| GeoLite2 有城市 20 | 20 | 20 | 全部保留，**0 处被改写**（只补空缺规则成立） |
| §5.2 两个 | 2 | 2 | 南昌新增、孝感保留 |
| **合计 102** | **97** | **48** | 家宽 80 个：省 **75/80（94%）**、市 **26/80（33%）**；原 GeoLite2 家宽省/市均为 0 |

### 冲突清单（conflicts.csv，35,781 行）

| 种类 | 行数 | 说明 |
|---|---|---|
| city_differs | 3,039 | 两边都有城市且不同，纯真胜出 |
| city_removed | 1,548 | 纯真只有省，GeoLite2 的城市被按规则移除（见已知缺陷） |
| province_differs | 447 | 省不同，纯真胜出 |
| country_differs | 104 | GeoLite2 标为外国、RIR 分配给 CN 的网段，纯真胜出 |
| ipv6_city_added | 24,745 | IPv6 叠加新增的市（GeoLite2 原无省市） |
| ipv6_province_added | 5,897 | IPv6 叠加新增的省（只有省，无市） |
| city_added（仅计数） | 72,665 条 CIDR | GeoLite2 无城市、纯真补上市——本次合并的主要收益 |
| province_added（仅计数） | 12,763 条 CIDR | GeoLite2 只有国家、纯真补上省 |

抽查：从 city/province_differs 中随机抽 40 行用 ip2region 独立验证，
纯真城市正确 23 行、GeoLite2 城市正确 2 行、12 行三方各执一词
（多为运营商大池、公司网段，本就难以精确定位）、省一级纯真正确 2/3。
即两库冲突时，纯真胜出的规则在可判定样本中约 23:2 占优。
（该抽查针对 v1 的纯真 FW 2024 版；v2 换 metowolf 2026-11-04 版后
未重抽，冲突总数由 5,147 变为 5,138 行，结构基本相同。）

## 本次构建的规模

- IPv4：纯真 CN 记录 349,047 条，覆盖 326,327,305 个大陆地址；
  聚合为 389 组、93,567 条 CIDR。
  CIDR 来源：GeoLite2 自带城市 67,511 条；省会坐标兜底 14,683 条
  （纯真只有省的组）；拼音城市 + DB-IP 坐标 5,819 条；
  拼音城市 + 手工地级市驻地坐标 3,659 条；
  拼音城市 + GeoLite2 英文名坐标 1,895 条。
- IPv6：GeoCN 网段 67,284 条 + qqwry.ipdb 大陆记录 5,130 条，
  聚合为 365 组、32,303 条候选 CIDR，实际插入 30,642 条
  （GeoCN 来源 31,767 条、ipdb 补缺 536 条；338 个市级组、
  27 个省级组）。GeoCN 的 67,284 条网段中 88% 有市级码
  （59,360 条），其余 12% 只有省级码。
- 111 个城市的英文名来自拼音（无 GeoNames 编号），其余来自 GeoLite2。

## 已知缺陷与取舍

1. **1,548 条 CIDR 丢了 GeoLite2 的城市**：纯真对这些网段只给到省，
   按任务书 §4.4 不回填 GeoLite2 的旧城市，umami 上这些访客只显示
   到省。如果你更看重“有城市显示”而非“城市一定准”，可以改规则为
   省级记录时保留 GeoLite2 的城市——改一行配置即可，见
   `build/merge_qqwry.py` 中 province-only 分支的注释。
2. **111 个拼音拼写城市**：英文名是拼音推导的（如 Lüliang、Yanbian），
   没有 GeoNames 编号，坐标来自 DB-IP 中位数或手工驻地坐标。
   其中 48 个城市的坐标是手工标注的地级市驻地概略值（约 10 公里精度，
   `accuracy_radius=100`，见 `merge_qqwry.py` 的 `CITY_COORDS` 表）。
3. **“Huangshan City”“Baise City”“Bazhong City”**：这是 GeoLite2
   自身的英文名（为与山名/地名区分），成品如实保留，不是拼写错误。
4. **IPv4 源已换成每周更新的 metowolf 版**：v1 的纯真 FW 版冻结在
   2024-09-25，v2 起改用 metowolf 每周从纯真 CZDB 转制的 .dat
   （当前 2026-11-04 版，与 FW 版随机抽样 95.1% 一致）。metowolf
   个别改动存疑（如某美国 AWS 段标成香港、某北京段标成英国），
   但 RIR 守卫会拦住跨国误标；重建时 `build.sh` 会自动取最新版。
5. **GeoCN 已 7 个月未更新（2026-04-18）**：IPv6 主源的最后发布是
   2026-04-18，仓库标注“随缘更新”、无 LICENSE 文件。新建/调整的
   IPv6 号段不会出现在其中；若它长期停更，可改用 qqwry.ipdb 全量
   （省覆盖约 95%，但市覆盖只有约 18% 且多为直辖市）。
6. **GeoCN 的 IPv6 覆盖稀疏且两库分歧大**：家宽样本上 GeoCN 只有
   约 25% 有省、约 16% 有市；它覆盖的移动样本里 8/9 是杭州
   （330100），集中度异常，可能是某大段的真实归属，也可能是回退
   值，无法从现有数据证实。GeoCN 与 qqwry.ipdb 同时有省时只有
   约 4 成一致（10/23），电信/联通样本上几乎全不一致，省一级
   谁对谁错目前判不出来——成品按“GeoCN 优先、ipdb 补省”的规则
   取值，省一级的 IPv6 结果可信度低于 IPv4。
7. **2 处海外“差异”实为纠错**（见 §5.3）：GeoLite2 把 2 个中国网段
   标成日本/香港，RIR 分配数据证明是中国的，成品按中国处理。
8. **城市冲突中约三成三方各执一词**：运营商省级大池、云厂商 anycast
   段（如 119.29.29.29 腾讯云 DNS，成品取北京，GeoLite2 取广州，
   DB-IP 取新加坡）没有唯一正确答案；`conflicts.csv` 列出了全部
   5,138 处 IPv4 冲突，可逐行抽查。

## 文件清单

- `GeoLite2-City-CN.mmdb` — 成品数据库
- `conflicts.csv` — 两库不一致的网段（网段、抽查 IP、种类、双方结果）
- `README.md` — 本文件
- `SHA256SUMS` — 上述文件的 SHA256
- `build/` — 可重复构建脚本（`build.sh`、`Dockerfile`、`merge_qqwry.py`、
  `merge_ipv6.py`、`dbip_coords.py`、`prefecture_cities.json`、
  `division_cities.json`、`cmd/extract_geolite`、`cmd/extract_geocn`、
  `cmd/walk_ipdb`、`cmd/build_mmdb`、`SOURCES.sha256`）
- `work/` — 构建中间产物（GeoLite2 提取表、合并后的 CIDR、验证脚本与结果）
- `data/` — 下载的源数据（GeoLite2、纯真、DB-IP、APNIC 分配文件等）
