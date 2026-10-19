---
name: pristima-api
description: 通过 Pristima XML API（PtsAPIServlet）直查 Pristima 数据库里的专题原始业务数据——方案信息、动物信息、体重、临床观察、样本、给药、病理、DART 全系列等 60+ 分类，以及事件表增量同步。用户要查询报表服务 20 张已实现报表之外的原生数据、需要某类原始记录、或要做增量数据同步时使用。只读；支持复用已有 JSESSIONID，避免反复登录撞 210064 会话上限。
required-secrets:
  - {name: PTS_USER, optional: true}
  - {name: PTS_PASSWORD, optional: true}
  - {name: PTS_API_BASE, optional: true}
  - {name: PTS_SITE_ID, optional: true}
  - {name: PTS_LANGUAGE, optional: true}
  - {name: PTS_JSESSIONID, optional: true}
---

# Pristima XML API 客户端

本技能封装 Pristima（Xybion）官方 XML-over-HTTP API（`PtsAPIServlet`），让 Agent 能**直查 Pristima 数据库中的原始业务数据**。它比 `pristima-report-agent`（已实现的 20 张格式化报表）更底层：覆盖方案、动物、体重、临床观察、样本、给药、剖检、病理、DART（发育与生殖毒性）等全量专题数据，并支持事件表增量同步。

**分工**：用户要"报表/PDF/已实现的那 20 张" → 用 `pristima-report-agent`；用户要报表之外的**原始数据、特定记录、事件增量、方案元数据**，或报表服务覆盖不到的领域（DART、样本、给药、幼仔等）→ 用本技能。

## 硬性约束

1. **只读**。文档里的更新/插入/写入类 API（`New Labwise Protocol`、`New Labwise Colony`、`StudyEventUpdate`、`RangeUpdate`、`IntefaceTransmissionInsert`、`IntefaceErrorInsert`）已按要求全部移除，本技能只保留读取数据的 API，**任何情况下都不发送写操作**；客户端脚本也会硬性拒绝写入类 Category 和 `SetPublished=Y`（改写事件表状态）这类带写副作用的参数。
2. **优先复用已有会话，不要反复登录**。有可用 `JSESSIONID` 时（脚本已内置一个
   长期会话；也可用 `--jsessionid` / `--jsessionid-file` / `PTS_JSESSIONID` /
   非空 `--cookie-file` 覆盖），直接查询：**不执行 GET 握手、不登录，也不会自动
   logout 这个复用会话**。反复 `session`/`login` 只会占用服务端 20 个会话名额，
   最终撞 `210064`。显式 `--cookie-file` 会屏蔽内置会话。
3. **不要用建会话命令"测试"已有 cookie**。`connect`、`session`、`register`、
   `login` 都会新建或覆盖服务端会话；`GET` 握手会覆盖会话里的 handler，
   可能把本来可用的登录态弄丢。已有 cookie 就直接 `query`。`session` 检测到
   cookie 文件里已有 JSESSIONID 时会拒绝执行，只有显式加 `--force` 才重建。
4. **只有本命令新建的会话才自动退出**。没有 cookie 时用
   `query --with-session` / `batch` / `session` 建会话，查询完默认 logout；
   复用会话默认保留。要主动释放名额，单独执行 `logout --jsessionid-file ...`
   （或对相应 cookie 执行 `logout`），不要在查询里顺手把用户的长期会话杀掉。
   未显式指定会话的 `logout` 默认拒绝退出内置长期会话，必须加 `--force`。
5. **同一 JSESSIONID 必须串行**。服务端一个会话只有一个可变的请求 handler，
   并发请求会串包/破坏会话。脚本按 cookie 文件或 JSESSIONID 哈希加跨进程锁
   （`--lock-timeout`，默认 300 秒），但锁只在同一主机/容器内有效；跨容器仍
   需外部队列或单会话代理。
6. **凭据与 cookie 都不外泄、不回显**。现网连接信息（含凭据和长期 JSESSIONID）
   明文内置于脚本 `DEFAULT_*` 常量，本 skill 目录禁止外发/开源；任何输出中不得
   出现密码或 JSESSIONID 值，也不要放进 URL。cookie 优先用 `--jsessionid-file`
   或平台 secret 注入；直接在命令行传 `--jsessionid` 会留 shell 历史/进程列表，
   非必要不用。cookie 是 bearer 凭据：泄露后仅改密码不一定能杀死已有 API 会话，
   必须 logout/invalidate 会话或重启 API 应用。
7. **参数照抄契约**。Category 名与 Tag 名必须与 [API 参考](api-reference.md) 逐字一致（包括文档遗留的拼写异常，如 `InterfaceError` 的请求参数 `ErrorDate From` tag 名带空格）。不要"纠正"拼写、不要臆造参数。
8. **日期格式**：`dd-mmm-yyyy hh:mm:ss`（英文月份缩写，如 `14-Jun-2008 09:00:00`），时区按**专题所在站点**换算，与登录用户无关。
9. 服务不可达或返回 `pts_rs_failure` 时，最多自动重试一次；再次失败后报告实际错误，不猜测结果。

## 连接信息（脚本内置默认 + 环境变量覆盖）

**现网连接信息已内置在脚本里**（`scripts/pts_client.py` 顶部 `DEFAULT_*` 常量），
开箱即用，命令不需要任何账号/地址参数。同名环境变量存在时优先覆盖（换账号/换环境
时用）：

| 环境变量（可选覆盖） | 内置默认值 | 说明 |
|---|---|---|
| `PTS_API_BASE` | `http://10.0.27.27/hubeipro_api/servlet/PtsAPIServlet` | 完整 URL（**用 IP**：沙箱解析不了内网主机名；zone=hubeipro_api，库实例 HUBEIPRO） |
| `PTS_USER` | `liumingli` | 现网 API 用户（具 API data output 权限） |
| `PTS_PASSWORD` | （内置） | 现网凭据，明文内置于脚本 |
| `PTS_SITE_ID` | `21` | Topgenxs 站点 |
| `PTS_LANGUAGE` | `0` | 0=英语 |
| `PTS_JSESSIONID` | （内置长期会话） | 已有会话的 JSESSIONID；**敏感**，优先用 `--jsessionid-file` 或平台 secret 注入；未注入时使用脚本内置值 |

> ⚠️ **凭据与 JSESSIONID 明文内置于脚本**：本 skill 目录禁止外发、禁止推送公开仓库
> （建议生产部署时放到 `skills/custom/`，该目录不进 git）。凭据一旦泄露，先到
> Pristima 侧改密，再改脚本里的 `DEFAULT_*`。JSESSIONID 泄露的处理见硬性约束第 6 条。

- **deerflow 沙箱内（生产）**：无需任何注入即可使用（沙箱不继承宿主环境变量，
  所以 .env 传不进来是预期行为）。frontmatter 里的 `required-secrets` 全部标记
  optional——调用方不在 `config.context.secrets` 带值也照常运行，带了则同名环境变量
  覆盖内置默认。与 llm-wiki 读取 `$LLM_WIKI_API_TOKEN` 的方式一致：脚本进程直接读
  环境变量（有）或内置默认（无）。`PTS_JSESSIONID` 也有内置长期会话：`query` /
  `choices` / `send` / `batch` 在没有任何 cookie 参数时会自动复用它，不登录、不
  logout；`session` / `connect` / `register` / `login` 不会读取它。显式提供
  `--cookie-file` 时内置会话不参与（让 `session` 建出的新 jar 能正常使用）。
- **本机直跑脚本**：什么都不用设；要覆盖时 PowerShell 里
  `$env:PTS_USER='...'; $env:PTS_PASSWORD='...'`（当前窗口有效）。
  命令行参数（`--base-url`/`--user`/`--password`/`--site-id`/`--language`）同样仅作
  覆盖用。`PTS_DEVICE_ID` 现网用不到。
- `env-check` 只报变量名和来源（`env`/`builtin`/`unset`），绝不回显值；
  `PTS_JSESSIONID` 未注入时显示 `builtin`（使用脚本内置长期会话）。

### 生产实测要点（2026-10-10 实测，与文档有出入的地方）

1. **Doctype 大小写**：`PTS_RQ_STUDY_DATA` **必须全大写**（小写实测被拒
   `Key=213002 Invalid request string`）；`pts_rq_device_access` / `pts_rq_login` /
   `pts_rq_logout` 小写实测可用。脚本已按实测值内置。
2. **设备访问**：现网每个新会话都用 `InitialDeviceName=True` + 固定设备名重复注册即可
   （同名重注册会返回已有 DeviceID）。**必须省略 `InstallDevice` 标签**——实测带上它会因
   设备名唯一性被拒 `Key=18001`，且该失败会让会话被服务端判死（后续全部 401
   Session not found），只能重新 GET 握手。`PTS_DEVICE_ID` 用不上。
3. **GET 握手返回的是 HTML**（`<BODY> Connection accepted </BODY>`），不是 XML；
   新会话的 cookie 通常是 `JSESSIONID=xxx.ptstappserver`。**复用 Postman 等已有 cookie
   时不要把值截断/重拼后缀**——脚本在 `--jsessionid` 模式下按原值发送。
4. **响应 XML 无命名空间**；真实响应字段可能比文档多（实测 `ProtocolInfo` 多
   `AutoOutputFlag` / `StartDate` / `DatabaseInstance`），解析要容错，不要按文档字段
   集做严格校验。
5. **实测确认文档的两处怪癖**：DART 胎仔观察（`FetalObs`）的响应父标签确实叫
   `GrossObsInfo`（三层：`GrossObsInfo → TissueInfo → FindingInfo`）；日期格式确实是
   `dd-mmm-yyyy hh:mm:ss`。

## 会话复用（首选，避免 210064）

服务端 `PtsAPIServlet` 在 POST 时直接复用 `HttpSession` 里已有的
`PostSessions.SessionHandler`，**不会重新认证**。所以一个有效的 JSESSIONID
可以跨天/跨进程直接查询，不需要重新登录。本部署还满足：

- `WEB-INF/web.xml` 的 `session-timeout` 是 `-1`；
- `API.ini` 没有 `SessionTermination`；
- `PtsAPIServlet` 本身不启动 `PtsSessionMonitor`。

因此**会话不会因空闲自动过期**：只有干净 logout、API 应用/服务器重启或显式
invalidate 才会释放。等待 10/30 分钟不会释放名额。

### 拿到 JSESSIONID 后的正确用法

脚本已内置一个长期 JSESSIONID：**不传任何 cookie 参数**的 `query` / `batch` /
`choices` / `send` 会直接复用它，不登录、不 logout。要换会话时按下面的优先级提供：

1. `--jsessionid` / `--jsessionid-file`（最高）；
2. `PTS_JSESSIONID` 环境变量 / 平台 secret；
3. 脚本内置的长期会话（最低）。

显式提供 `--cookie-file` 时，内置会话不参与，方便 `session` 建出的新 jar 正常使用。

```bash
# 推荐：写入受保护文件，避免命令行/进程列表泄露；/mnt/user-data 在沙箱重建后仍在，
# /tmp 会丢。文件权限收紧到 600。
printf '%s' "$PTS_JSESSIONID" > /mnt/user-data/workspace/.pts_jsid
chmod 600 /mnt/user-data/workspace/.pts_jsid

python scripts/pts_client.py query \
  --jsessionid-file /mnt/user-data/workspace/.pts_jsid \
  --category ProtocolInfo --param StudyName=A2024042-T034-01 --json
# → 不登录；查询成功后默认保留该会话（结果里 session_reused=true）

# 使用脚本内置会话：不传 cookie 参数即可
python scripts/pts_client.py query \
  --category ProtocolInfo --param StudyName=A2024042-T034-01 --json
```

也可以直接传值（会进入 shell 历史/进程列表，慎用）：

```bash
python scripts/pts_client.py query --jsessionid 'A1B2...ptstappserver' \
  --category ProtocolInfo --param StudyName=A2024042-T034-01 --json
```

或者由平台把 `PTS_JSESSIONID` 注入环境变量，命令里完全不出现 cookie：

```bash
python scripts/pts_client.py query --category ProtocolInfo \
  --param StudyName=A2024042-T034-01 --json
```

**注意**：

- 已有 cookie 时**不要**再跑 `session`、`connect`、`register`、`login`。GET 握手会
  覆盖服务端会话 handler，可能直接毁掉这个登录态。
- 复用会话查询失败返回 401 时，默认会**自动重建一次**（GET→设备→账号登录）并重试；
  重建出来的新会话默认会在结束时 logout，除非加 `--keep-session`。不想自动登录
  （例如已经撞 210064）就加 `--no-login`，让命令直接报错。
- 同一 cookie 的多个任务要串行。脚本会用
  `<cookie-file>.lock` 或 JSESSIONID 哈希命名的锁文件做跨进程串行；跨容器并发仍需
  外部代理/队列。
- `--cookie-file` 要 Netscape/Mozilla 格式的 cookie jar，不是 Postman 的原始
  `JSESSIONID=...` 文本。只有原始值就用 `--jsessionid`/`--jsessionid-file`。
- 需要主动释放名额时，显式执行
  `logout --jsessionid-file ...`（或 `logout --cookie-file ...`）。这会把该会话
  logout 掉，后续不能再用同一个 cookie。未指定会话的 `logout` 默认不会退出内置
  长期会话，确认要退出必须加 `--force`；退出后内置值即失效，需要更新
  `DEFAULT_JSESSIONID` 或改用新的 JSESSIONID。

## 新建会话流程（没有可复用 cookie 时）

生产实测的顺序（**不可省略或颠倒**，跳过设备登录会被服务端拒绝）：

1. **GET 握手**（`connect`，或由 `session`/`query --with-session`/`batch` 内部完成）。
2. **设备登录**（`register`）：`InitialDeviceName=True` + 固定设备名 + 账号密码。这是现网
   **唯一可用方式**——不要用 `device-access`（它需要已注册的 DeviceID，现网没有）。
3. **账号登录**（`login`）：API 用户的 UserID/Password（+ Language），登录后约 3 秒
   会话才就绪。
4. **获取数据**（`query` / `choices`）：同一会话内可多次调用。
5. **退出账号**（`logout`）：**本命令新建的会话**在结束时默认退出
   （`query --keep-session` 可保留；`batch --no-logout` 可保留），避免留下孤儿会话。
   复用已有会话则默认保留，不要自动退出。

**推荐写法**：

- 没有可复用 cookie 时，单条查询用
  `query --with-session`（建会话→查询→退出一条命令完成）；注意脚本内置长期会话
  存在时，`--with-session` 也会优先复用它，不会新建。
- 多条查询用 `batch`（建会话→顺序查询→会话失效自动重建→末尾退出）；
- 需要把会话留给后续多条命令时，用 `session --cookie-file <jar>` 建会话，
  后续 `query --cookie-file <jar>` 会复用并保留它（显式 jar 会屏蔽内置会话）；
  用完再显式 `logout`。`session` 发现该 jar 里已有 JSESSIONID 会拒绝覆盖；
  确认要重建才加 `--force`。
- 有现成 JSESSIONID 时，直接用上一节的复用写法，**不要建会话**。
- 确实要绕过内置会话、强制新建一条一次性会话：显式给一个空 jar，例如
  `query --with-session --cookie-file /mnt/user-data/workspace/new.txt ...`。

### 常见错误速查（生产实录教训）

| 错误 | 含义 | 正确处置 |
|---|---|---|
| `Key=210064` 会话上限 | 该账号成功登录且未退出的会话数达到服务端 `max_user_connection=20`（站点范围），**不是 ScreenLock，也不是 10 分钟锁屏**。每次成功 login 计数 +1，干净 logout 立即 -1；本部署不 logout 就永不自动释放。只拦新 login，已有会话仍可查询 | 停止重复登录/重试；优先复用现有 JSESSIONID 直接查询；要释放名额就 logout 旧会话或重启 API 应用。不要等"锁屏过期"，没有这个计时 |
| `Key=214002` Not signed on | **不是会话问题**：Category 名大小写不对（服务端实测大小写敏感）或账号对该分类数据无授权。实测 4 个拼写修正：`CSection`、`ProSubGroup`、`AnimalPhase`、`SampleDrawlist`——客户端会自动纠正并在结果里带 `category`（原拼写见 `category_requested`） | 先核对拼写（api-reference 各条目有 ⚠️ 标注），再找 IT 核查账号授权；**不要重建会话**，重建只会多占一个名额 |
| `Key=213002` Invalid request string | Doctype 小写（study_data 必须大写 `PTS_RQ_STUDY_DATA`）或参数格式不对 | 对照 api-reference.md 检查请求 |
| HTTP 401 Session not found | 服务端已没有这个会话（logout 过、API 重启、会话被 invalidate），**不是"空闲 30 分钟过期"** | 有 cookie 时 `query` 默认重建一次；`batch` 会自动重建；加 `--no-login` 则直接报错。不要为了"续期"反复登录 |

### 现网实测的时序坑（务必知道）

- **登录后约 3 秒会话才就绪**：登录完立即查询会失败（服务端会话传播延迟）；
  `session`/`batch`/`query --with-session` 内置 `--login-wait`（默认 3 秒）自动等待，
  手工分步时自己 sleep。
- **`SessionOut=30` 只是登录响应里的字段**，本部署不执行空闲过期（见上）；不要据此
  判断会话会"30 分钟后失效"。
- **`ScreenLock=10` 只是客户端锁屏设置**，与 210064 无关；210064 的唯一原因是 20 个
  未退出会话的名额已满。
- 反复重建会话会连续消耗名额——宁可等 3 秒、复用一个会话，也不要反复
  connect+register+login。

## 常用查询套路

在本技能目录执行（Linux/bash，即生产沙箱形态；本机 Windows 用 PowerShell 把路径
换成 `.\scripts\` 即可）：

```bash
# 连接信息：脚本内置现网默认值，同名环境变量可覆盖（与 llm-wiki 读
# $LLM_WIKI_API_TOKEN 的方式一致），命令里不出现任何账号密码。
# 会话前可先看各变量的来源——只报名字与来源（env/builtin/unset），不报值：
python scripts/pts_client.py env-check
#   → {"sources": {"PTS_API_BASE": "builtin", "PTS_USER": "builtin",
#                  "PTS_JSESSIONID": "builtin", ...}, "ok": true}

# 单条查询（默认复用脚本内置长期会话：不登录、不自动 logout）
python scripts/pts_client.py query --category ProtocolInfo \
  --param StudyName=A2024042-T034-01 --json

# 换用指定的已有会话（推荐）：不登录、不自动 logout
python scripts/pts_client.py query --jsessionid-file /mnt/user-data/workspace/.pts_jsid \
  --category ProtocolInfo --param StudyName=A2024042-T034-01 --json

# 多条查询推荐用 batch：有 cookie 就复用并保留；没有 cookie 就建会话、末尾退出
# 注意 Category 名大小写敏感：剖宫产用 CSection（大写 S），Csection 会被拒 214002
cat > /mnt/user-data/workspace/batch.json <<'EOF'
{"queries": [
  {"category": "CSection", "params": {"StudyName": "A2024042-T031-01"},
   "output": "/mnt/user-data/workspace/cs_A2024042-T031-01.json"},
  {"category": "CSection", "params": {"StudyName": "A2024042-T031-02"},
   "output": "/mnt/user-data/workspace/cs_A2024042-T031-02.json"}
]}
EOF
python scripts/pts_client.py batch --spec /mnt/user-data/workspace/batch.json \
  --jsessionid-file /mnt/user-data/workspace/.pts_jsid
# 中断后补跑加 --resume：跳过已有非空输出，不重复请求、不覆盖已拿到的数据
# 复用会话默认保留；只有新建/重建的会话才需要 --no-logout 来保留
# 若确实要主动释放会话名额：python scripts/pts_client.py logout --jsessionid-file ...

# 分步执行（把会话留给后续多条命令）：先建一次，后续 query 复用并保留
python scripts/pts_client.py session --cookie-file /mnt/user-data/workspace/pts.txt
python scripts/pts_client.py query --cookie-file /mnt/user-data/workspace/pts.txt \
  --category ProtocolInfo --param StudyName=A2024042-T034-01 --json
#   → session_reused=true，不会自动 logout；用完显式 logout --cookie-file ...

# 胎仔外观观察（实测三层结构 GrossObsInfo→TissueInfo→FindingInfo）
python scripts/pts_client.py query --category FetalObs \
  --param StudyName=A2024042-T034-01 --param MeasurementName='Fetal Observations' --json

# 事件增量（新事件，状态 1=New）
python scripts/pts_client.py query --category StudyEvent \
  --param Status=1 --param Studies.StudyName=A2024042-T034-01

# 主数据：测量/参数/组织清单
python scripts/pts_client.py query --category Measurement
python scripts/pts_client.py query --category Parameter --param ActiveFlag=Y

# 大结果集：默认先探测条数、超阈值自动分段（结果落盘 .partNNN.xml）
python scripts/pts_client.py query --category BodyWeight \
  --param StudyName=A2024042-T034-01 --output body.xml
# 或分段后合并成单个 JSON（没给日期范围时借 MeasurementType → DataDateRange 的范围）
python scripts/pts_client.py query --category BodyWeight \
  --param StudyName=A2024042-T034-01 --param MeasurementType=101 --json
```

通用形式：`query --category <Category> --param Tag=Value ...`，`--param` 可重复；点号表示嵌套（如 `Studies.StudyName` 多个专题）。响应默认原样输出 XML，加 `--json` 转 JSON，加 `--output <路径>` 保存原始 XML（不覆盖已有文件）。所有 Category 的请求参数与响应结构见 [API 参考](api-reference.md)。

**会话选择器**（优先级从高到低）：

- `--jsessionid <值>` / `--jsessionid-file <路径>`：直接提供 Postman 等来源的原始
  JSESSIONID；原值发送、不改写后缀。文件方式避免泄露到命令行，推荐。
- `PTS_JSESSIONID`：平台 secret 注入，等价于 `--jsessionid`；只对支持复用的命令生效。
- 脚本内置长期会话：以上都没有且没有显式 `--cookie-file` 时自动使用。
- `--cookie-file <jar>`：Netscape 格式的 cookie jar，可跨命令复用；显式提供时屏蔽
  内置会话；为空时配合 `--with-session`/`session` 新建。
- `--no-login`：cookie 失效时不要自动登录，直接报错（210064 期间建议加）。
- `--keep-session`：本次新建/重建的会话也保留；复用会话本来就保留。
- `--no-logout`（仅 `batch`）：不退出本次新建/重建的会话；复用会话本来就保留。
- `--lock-timeout`：等待同一会话锁的秒数（默认 300）；超时会报错而不是并发抢同一个会话。

**大结果集自动分段**：`query` 默认先发一次 `CountOnly=Y` 探测条数（只回数字，开销可忽略）；超过 `--max-records`（默认 10000）时按 `StartDateTime`/`EndDateTime` 时间窗二分自动分段抓取（各数据 API 按录入时间过滤）。分段需要日期范围：请求里给了就直接用；没给但有 `MeasurementType` 时借 `DataDateRange` 的日期范围；两者都没有会报错并提示补充（可调高 `--max-records` 或缩小筛选）。分段结果落盘为 `--output` 的 `.part001.xml` 系列，或加 `--json` 合并成一个 JSON。`--no-probe` 跳过探测直接单次查询；不支持 CountOnly 的 Category 会自动退回单次查询。

## 数据口径要点（答用户前必须知道）

- **query --json 输出形状**：stdout 是 `{"success": true, "response": {...},
  "category": "...", "session_reused": true/false, "logout": "...", ...}`；数据在
  `response.PTS.<父标签>` 下——同标签多条记录是 **list**、单条是 **dict**。例：专题清单
  `response.PTS.ProtocolInfo`（list），剖宫产 `response.PTS.CsectionInfo`（list，
  每项再套 AnimalInfo）。失败时 stderr 输出 `{"success": false, "error": "..."}`
  且退出码非 0，**先看 success 再取数据**。
- **会话状态字段**：`session_reused=true` 表示复用了传入/文件里的会话；
  `session_rebuilt=true` 表示原会话 401 后自动重建过；`logout` 说明本次是否退出了
  某个会话。`batch` 另有 `session_rebuilds` 和逐项 `results`。
- **Category 名即函数名**，全集与用途见 api-reference.md 的目录；同一测量类型可能有多个测量名，`MeasurementName` 是可选参数，计数与数据按测量名分开返回。
- 带 `CountOnly=Y` 先取条数再取明细，避免一次拉全量；`N` 限制最大记录数。
- `StartDateTime`（含）/`EndDateTime`（不含）过滤的是数据**录入/修改时间**，不是业务发生时间（个别 API 例外，见参考）。
- 多数响应字段含 `EntryOperator*`（录入人）、`Sign*`（签名）、`DeleteFlag/EditFlag`（删除/编辑标记）；`DeleteFlag=Y` 时除主键外还会返回交替键中非空的列，这是接口契约，不是脏数据。
- 文档遗留异常（父标签名与章节标题不符、个别 tag 名含空格、`½` 等提取伪影）已逐条记录在 api-reference.md 末尾，遇到对不上的响应先查那里。

## 事件表（增量同步）

`StudyEvent` 查询 EVENT 表（按发生顺序）；每条事件带 `EventDetail` name/value 对，其中 `Type=3` 的是记录主键，可用于后续按主键精确查数。事件状态：`1=New / 2=Published / 3=Acknowledged / 4=Erroneous / 5=Deferred / 6=Ignore Forever`。api-reference.md 各条目里标注"触发事件：无/未实现"的 API 没有事件触发器，事件接口查不到它们的计数和 ID，只能按专题/日期直接拉数。

## 脚本

[scripts/pts_client.py](scripts/pts_client.py) 仅依赖 Python 标准库，子命令：
`connect` / `register` / `device-access` / `login` / `session` / `query` /
`choices` / `send`（发送任意准备好的 XML）/ `logout` / `batch` / `env-check`。
结果以 JSON 输出（`{"success": true, ...}`），错误以
`{"success": false, "error": ...}` 输出到 stderr 并返回非零退出码。
`query` / `choices` / `send` / `logout` / `batch` 支持 `--jsessionid` /
`--jsessionid-file` / `PTS_JSESSIONID`，并在没有显式会话时使用脚本内置长期会话；
建会话类命令不支持（避免误覆盖已有会话）。`session` 在 cookie 文件已有 JSESSIONID
时默认拒绝执行，`--force` 才会重建。未指定会话的 `logout` 默认拒绝退出内置长期
会话，确认要释放名额必须加 `--force`。

## 使用范围

本技能内容只作内网使用，不要随开源仓库对外发布；目录内脚本含现网凭据与
会话复用入口，按敏感资产管理。
