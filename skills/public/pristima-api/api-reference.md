# Pristima XML API 参考

协议：HTTP + XML；初始 GET 建会话拿 cookie，后续 POST XML（`<PTS>...</PTS>`）到
`http://<API服务器>/<zone名>/servlet/PtsAPIServlet`。请求 Doctype 前缀 `pts_rq_`，
响应前缀 `pts_rs_`；失败响应 Doctype 为 `pts_rs_failure`（格式见文末"错误响应"）。

**现网实测（2026-10-10，`http://10.0.27.27/hubeipro_api/servlet/PtsAPIServlet`——
用 IP，沙箱解析不了内网主机名 PTSPSaAPI；库实例 HUBEIPRO，SiteID=21，Language=0）**：
- `PTS_RQ_STUDY_DATA` 的 Doctype **必须全大写**，小写被拒
  `Key=213002 Invalid request string`；`pts_rq_device_access` / `pts_rq_login` /
  `pts_rq_logout` 小写实测可用。`CSection` 与 `Csection` 等 Category 名大小写以
  实测为准。
- 设备访问每会话带 `InitialDeviceName=True` + 固定设备名重复注册即可（同名重注册返回
  已有 DeviceID）；**必须省略 `InstallDevice` 标签**——带上会因设备名唯一性被拒
  `Key=18001`，且该失败会让会话被服务端判死（后续全部 401 Session not found）。
- GET 握手返回 **HTML**（`Connection accepted`），不是 XML；会话 cookie 为
  `JSESSIONID=xxx.ptstappserver`（也可能是 `.ptspsaapi`，后缀由服务端节点决定，
  复用已有值时原样发送，不要重拼）。
- `CountOnly=Y` 的响应把 `<Count>` 放在**记录父标签内**（如 `<BodyWeightInfo><Count>1475`
  `</Count></BodyWeightInfo>`），不是文档表格里的顶层；客户端解析兼容。
- 响应 XML **无命名空间**；真实响应字段可能比文档多（实测 `ProtocolInfo` 多
  `AutoOutputFlag` / `StartDate` / `DatabaseInstance`），解析要容错。
- 实测确认：`FetalObs` 响应父标签确实是 `GrossObsInfo`（`GrossObsInfo → TissueInfo →
  FindingInfo` 三层）；日期确实是 `dd-mmm-yyyy hh:mm:ss`。

**Tag 名一律保留文档原文**（含遗留拼写），照抄即可；文末"原文异常清单"记录了所有
已知坑（父标签名与章节不符、tag 名含空格、Required 列错位等）。

## 目录：Category 全集

**事件**：`StudyEvent`
**方案信息**：`ProtocolInfo`、`ProDoseGroup`、`ProShortText`、`ProCaging`、
`ProMicroTissue`、`ProGrossTissue`、`ProPhase`、`ProSubgroup`、`ProArticle`、
`ProArtShortText`、`ProSchedule`、`ProNecSchedule`、`ProParameter`、
`ProRelFinding`、`StudyBaselineData`、`ProSubGroup`（⚠️大写 G，`ProSubgroup` 被拒）
**选择项/主数据**：`Sites`、`Template Protocol`、`Protocol Definition`、
`Colony Definition`、`Active Species`、`All Species Related Strains`、
`Active Study Types`、`Active Study Subtypes`、`Active Supplier`、
`Available Colony Approvers`、`Available Study Approvers`、`Active Colony Numbering`
**动物**：`AnimalData`、`AnimalPhase`（⚠️文档写 `StudyAnimalPhase` 被拒）、`AnimalCage`
**In-life / 临床病理**：`BodyWeight`、`GenMeas`、`NonAnimalMeas`、`Memo`、
`SampleCollection`、`StudySampleResult`、`CellMorphology`、`SampleObs`、
`SampleTrack`、`SampleDrawlist`（⚠️小写 l，`SampleDrawList` 被拒）、`SampleRef`、`QCSampleResult`、`ClinicalObs`、
`ProductAdmin`、`FoodConsumption`、`FullFeeder`、`MassTracking`、`DirectDosing`、
`IndirectDosing`、`DataDateRange`
**剖检**：`OrganWeight`、`TermBodyWeight`、`GrossObs`、`TissueStatus`、`AnimalComment`
**病理**：`MicroObs`、`Correlation`
**DART（发育与生殖毒性）**：`MatingMon`、`EstrusCycleMon`、`EstrusObs`、`OvaryExam`、
`CSection`（⚠️大小写敏感，`Csection` 被拒）、`UterineExam`、`ProgenySex`、`FetalObs`、`Parturition`、`PupBodyWeight`、
`PupDirectDosing`、`PupClinicalObs`、`PupGenMeas`、`PupObs`、`LitterWeight`、
`DamPupData`、`MatingStatus`
**杂项**：`AgeRange`、`Measurement`、`Parameter`、`Tissue`、
`InterfaceTransmission`、`InterfaceError`、`ReportConfiguration`

---

## 一、会话与命令

### 1.1 请求流程

| 步骤 | Doctype / 命令 | 说明 |
|---|---|---|
| 1 | GET（无 XML 体） | 初始化连接，拿 cookie；响应 Connection_Accept |
| 2 | `pts_rq_device_access`（首次带 `InitialDeviceName=True`） | 设备注册/设备访问，取得 DeviceID |
| 3 | `pts_rq_login` | 用户登录（API data output 权限用户） |
| 4 | `pts_rq_study_data` / `pts_rq_choices` | 数据查询 / 选择项查询，可多次 |
| 5 | `pts_rq_logout` | 登出（仅本命令新建的会话；复用会话默认保留） |

- **复用已有 JSESSIONID 时跳过 1–3**：直接 POST 步骤 4。服务端 POST 只从
  `HttpSession` 取已有 handler，不会重新认证；不要先跑 GET/`session` 测活——
  GET 会覆盖 handler，可能毁掉原登录态。同一 JSESSIONID 必须串行。
- 客户端内置一个长期 JSESSIONID 作为默认复用会话；`--jsessionid` /
  `--jsessionid-file` / `PTS_JSESSIONID` 可覆盖，显式 `--cookie-file` 会屏蔽内置值。
  需要新建会话时用 `session --cookie-file <jar>`，后续 `query --cookie-file <jar>`
  使用该 jar；内置会话不会被退出（`logout` 未指定会话时默认拒绝，需 `--force`）。
- 本部署会话**不会空闲自动过期**（`web.xml` session-timeout=-1，`API.ini` 无
  `SessionTermination`）；`210064` 是该账号未退出登录数达到
  `max_user_connection=20`，不是 ScreenLock/10 分钟锁屏。
- 设备注册（现网实测）：每会话带 `DeviceName`、`DeviceLocation`、
  `InitialDeviceName=True`、`UserID`、`Password`、`Language`、`SiteID` 重复注册即可
  （同名重注册返回已有 DeviceID）；**必须省略 `InstallDevice`**，否则 `18001`
  且会话被判死。不需要 `device-access`/预存 DeviceID。
- `SiteID` 通过 `pts_rq_choices`（Module=Security、Category=Display、
  Location=Login、Name=Sites）查；`Language` 通过 `pts_rq_extended_choices`
  （Name=Languages）查（`Index`：0=英语，2=中文）。
- `pts_rq_logout` 带 `AccessStatus`。

### 1.2 数据查询（pts_rq_study_data）

```xml
<PTS>
  <Doctype>pts_rq_study_data</Doctype>
  <Category>BodyWeight</Category>
  <StartDateTime>14-Jun-2008 17:20:12</StartDateTime>
  <EndDateTime>20-Jun-2008 17:20:12</EndDateTime>
  <StudyName>08-0810</StudyName>
  <Type>0</Type>
  <N>100</N>
</PTS>
```

- 每个 Category 的可用参数见下文各条目；`StudyName` 是大多数数据类的必填项。
- 选择项类 Category（如 `Active Species`、`Sites`）只需 `<Category>` 本身。
- 响应 Doctype 为 `PTS_RS_STUDY_DATA`，含 `<Category>` 与按 Category 而异的父标签。

### 1.3 通用参数语义

- `StartDateTime`（含）/`EndDateTime`（不含）：多数 API 过滤数据**录入/修改时间**；
  少数（如 `SampleDrawList`）过滤业务日期，以各条目为准。
- `StudyName`：多数 API 可重复（重复多个专题）；事件查询里包在 `<Studies>` 内。
- `CountOnly=Y`：只返回条数；`N`：最大记录数（不给则全量）。
- `Types`：1=colony，2 或 null=study，缺省按 study。
- `Generation`：多代研究代数，单代为 0。
- 测量类 API 可带 `MeasurementName`（可重复）；不给则按测量名分组返回全部。

**客户端大结果集分段**（`pts_client.py query` 默认行为）：先发 `CountOnly=Y` 探测总条数，
超过 `--max-records`（默认 10000）时按 `StartDateTime`/`EndDateTime` 时间窗二分分段抓取；
无日期范围但有 `MeasurementType` 时自动借 `DataDateRange`（响应里的 StartDateTime/
EndDateTime 是**入库时间**）定范围。分段需 `--output`（写 `.partNNN.xml`）或 `--json`
（合并输出）；`--no-probe` 跳过探测。不支持 CountOnly 的 Category 自动退回单次查询。

### 1.4 数据格式

- 日期时间：`dd-mmm-yyyy hh:mm:ss`（英文月份缩写）；按**专题站点**时区换算。
  `StartDateTime`/`EndDateTime` 可带小数秒 `.ff6`。纯日期 `dd-mmm-yyyy`、纯时间
  `hh:mm:ss` 不做时区换算。
- 名称类字段：有外文名时同时返回 `Name` 与 `NameForeign`。
- 码值类字段：同时返回索引码 + 英文 prompt 值（外文模式登录时另给外文值）。

---

## 二、事件表与事件 API

### 2.1 EVENT / EVENT_DETAIL / EVENT_CONFIG

- `EVENT`：`EVENT_ID`（主键）、`EVENT_TYPE`、`STATUS`、`STATUS2`、`STUDY_NUMBER`、
  `SERVER_ZONE_NAME`、`DATE_TIME_ENTERED`、`LOCAL_TRANS_ID`。
- `EVENT_DETAIL`：`EVTDTL_ID`、`EVENT_ID`、`NAME`、`VALUE`、`TYPES`
  （1=Qualified 限定字段；2=Informational 信息字段；3=记录主键）、`EDIT_TYPE`
  （1=新增；2=删除；3=修改）。
- `EVENT_CONFIG`：配置想跟踪的事件类型与限定字段（`FIELD_NAME`/`FIELD_VALUE`/
  `EVENT_FLAG` Y/N；同类型多限定字段为 AND，同字段多值为 OR）。事件按发生顺序入库，
  超过 `Delete_events_after_days`（默认 60 天）自动清理。

### 2.2 StudyEvent（事件查询）

参数（均可选）：`StartDateTime`、`EndDateTime`、`StudyName`（可重复，包在
`<Studies>`）、`Status`（可重复）、`Status2`（可重复）、`EventType`（可重复）、
`TotalCountOnly`(Y/N)、`CountOnly`(Y/N)、`N`。

响应：每个事件一个 `<StudyEventInfo>`，含 `StudyName`、`EventID`、`EventType`、
`EventDateTime`、`Status`、`Status2`、`Count`（CountOnly/TotalCountOnly 时）与
多条 `<EventDetail Value="..." Type="n" EditType="n">NAME</EventDetail>`。

---

## 三、方案信息类（Category = 下列名称）

### 3.1 ProtocolInfo（方案信息）

- 参数：`StudyName`(N)、`Types`(N)、`SiteName`(N)、`SiteID`(N)、`ProtocolStatus`
  (N，1 Proposed/2 Active/3 Completed/4 Closed/5 Archived)、`IgnorePhase`(N)、
  `ProtocolID`(N)。都不给 → 返回全部专题清单（只有 ProtocolID+StudyName）。
- 响应 `<ProtocolInfo>`：ProtocolID、ProtocolNumber、StudyName、StudyTitle、
  DateTimeApproval、ProtocolStatus(Name)、NumGeneration、NumGroup、NumSubgroup、
  StudyType(ID/RefID/Name/Foreign)、StudySubType(…)、GLPStudy、HousingMethod、
  Species(ID/RefID/Name)、SubgroupStrain、SiteID/SiteName、Strain(ID/RefID/Name)、
  SubgroupSupplier、Supplier(ID/RefID/Name/Code/Location)、Types(TypesName)、
  ReassignmentWnd、SubgroupFromStart、StartingMale/Female、FromColony、
  ColonyName、CLProRefID、AupNumID/AupNumber、PlannedPHSTDate、PlannedSTDate、
  PlannedENDate、LeadPathologist(ID/RefID)、StudyDirector(ID/RefID)、
  EntryDateTime/EntryOperator(ID/RefID)、SponsorStudyName、StudySponsor。

### 3.2 ProDoseGroup（剂量组）

- 参数：`StudyName`(Y)、`Types`(N)、`PGRPNM_ID`(N)、`ProtocolID`(N)。
- 响应 `<ProDoseGroupInfo>`：ProtocolID、StudyName、Types、PretestPhEx、
  NumOfGroups；每组 `<ProGroupNameInfo>`（ProGrpNameID、GroupNumber、GroupType
  (Name/Foreign)、GroupName(Foreign)、Sex、GroupColor、EntryOperator*）；
  每代 `<ProGroupGenInfo>`（GroupNumber、Generation、MalesInGroup、FemalesInGroup、
  RouteOfAdmin、Compound）。

### 3.3 ProShortText（方案短文本）

- 参数：`StudyName`(Y)、`Types`(N)、`ProtocolID`(N)。
- 响应 `<ProTextInfo>`：ProtocolID、ProTextID、ProSubSecID、ProDefSubSecID、
  SubSectionName(Foreign)、SubSectionType(Name/Foreign)、Text、TextForeign、
  Required、Entry*。

### 3.4 ProCaging（笼位设置）

- 参数：`StudyName`(Y)、`Types`(N)、`ProtocolID`(N)、`Generation`(N，缺省 0)。
- 响应：ProtocolID、SameSubgroup；每阶段 `<PhaseCagingInfo>`（ProCagingID、
  ProPhaseID、PhaseName(Foreign)、MalesPerCage、FemalesPerCage、CageType(Name/Foreign)、
  Entry*）；每代 `<CagingGenInfo>`（ProCageRackID、Generation、NumOfRows、NumOfCols、
  Entry*）。

### 3.5 ProMicroTissue / ProGrossTissue（方案组织）

- 参数：`StudyName`(Y)、`Types`(N)、`MeasurementName`(N)、`Generation`(N，缺省 0)。
- 响应 `<TissueInfo>`：ProtocolID、MeasurementName(Foreign)、TissueID/RefID、
  ProTissueID、TissueName(Foreign)、TissueAbbr、Sex、Paired、RatioDecimal/Flag、
  OWDecimal、TBWDecimal、AddedTissue、Entry*；ProGrossTissue 另含 DeathStatusID/
  DeathStatus(Foreign)。

### 3.6 ProPhase（阶段）

- 参数：`StudyName`(Y)、`ProPhaseID`(N)、`Generation`(N，缺省全部代)。
- 响应 `<ProPhaseInfo>`：ProtocolID、ProPhaseID、StartDate、DayZero(Y/N)、
  Generation、PhaseType(Name/Foreign)（1 Pretest/2 Dosing/3 General/
  4 Randomization/5 Recovery/11 Gestation/12 Mating/13 Postpartum/14 Pretest Mating）、
  PhaseName(Foreign)、FootNote、NonAnimal、Types、Entry*。

### 3.7 ProSubGroup（亚组）

- ⚠️ **Category 名大小写敏感（实测）**：现网要用 `ProSubGroup`（大写 G）；
  `ProSubgroup` 被服务端拒（`Key=214002`）。

- 参数：`StudyName`(Y)、`ProtocolID`(N)。
- 响应 `<ProSubGroupInfo>`：ProtocolID、ProSubGrpID、SubGroupNumber、DayDiff、
  Males/FemalesInSubGroup、MaleName(Foreign)、FemaleName(Foreign)、StrainID(Name/
  Foreign)、SupplierID(Name/Code)、Entry*；每组/代/性别 `<GroupSubgroupInfo>`
  （GroupNumber、SubGroupNumber、Sex、Generation、NumOfAnimals）。

### 3.8 ProArticle（给药方案）

- 参数：`StudyName`(Y)、`Types`(N)、`PROART_ID`(N)、`ProtocolID`(N)、
  `IncludeSchedule`(Y/N，缺省 N)。
- 响应 `<ProArticleInfo>`：ProtocolID、StudyName、ProArticleID、Name(Foreign)、
  Abbreviation、Type(Name/Foreign)、Method(Name/Foreign)、Calculation(Name/Foreign)、
  Rate(RateUnits/RateType(Name/Foreign))、Tolerance、LotBatch、RouteOfAdmin、Entry*；
  若 IncludeSchedule=Y：`<ProArticleSchedule>`（ProPhsID、Generation、PhaseName、
  GroupNumber、SubGroupNumber、SubSubclass(Name/Foreign)、StartTP、ScheduledDays）；
  每化合物 `<ProCompoundInfo>`（ProCompoundID、CompoundCode、Long_Name、Biologic、
  Name、CompoundID/RefID、CompoundType(Name/Foreign)、CompoundForm(Name/Foreign)、
  CompoundCASNo、Calculation(Name/Foreign)、Expanded、Units、Decimal、ExpandFactor、
  ExpanderCompoundID/Name、Entry*）；每组剂量 `<ProGroupDosageInfo>`（GroupNumber、
  GroupType、ProCompoundID、Units、MaleDosage、FemaleDosage、StabilityUnits、
  Male/FemaleGroupStability）。

### 3.9 ProArtShortText（给药方案短文本）

- 参数：`StudyName`(Y)、`Types`(N)、`PROART_ID`(N)、`ProtocolID`(N)。
- 响应 `<ProArtTextInfo>`：ProtocolID、StudyName、ProArticleID、Name(Foreign)、
  ProTextID、ProSubSecID、ProDefSubSecID、SubSectionName(Foreign)、
  SubSectionType(Name/Foreign)、Text、TextForeign、Required、Entry*。

### 3.10 ProSchedule（测量计划）

参数、事件与响应结构见下文"ProSchedule"条目。

### 3.11 ProNecSchedule（剖检计划）

见下文"ProNecSchedule"条目。

### 3.12 ProParameter（方案参数）

见下文"ProParameter"条目。

### 3.13 ProRelFinding（方案相关发现）

见下文"ProRelFinding"条目。

### 3.14 StudyBaselineData（专题基线数据）

见下文"StudyBaselineData"条目。

---

## 四、选择项 / 主数据类

- `Sites`：用 `pts_rq_choices`（Module=Security、Category=Display、Location=Login、
  Name=Sites）→ `<Choice><Text>站点名</Text><Index>SiteID</Index></Choice>`。
- `Template Protocol` / `Protocol Definition` / `Colony Definition` /
  `Active Species` / `Active Study Types` / `Active Study Subtypes` /
  `Active Supplier` / `Active Colony Numbering`：`pts_rq_study_data` 只带
  `<Category>` → `<Choice><Text>..</Text><Index>..</Index><RefID>..</RefID></Choice>`
  （`Active Species` 等用 `pts_rs_extended_choices` 返回）。
- `All Species Related Strains`：同上，`<Choice>` 另含 `<Species>`。
- `Available Colony Approvers` / `Available Study Approvers`：同上（Text/Index/RefID）。
- 注意：Labwise 选择项类的 `Index`/`RefID` 可能重复（对不上数据表时），解析要容错。

## 五、错误响应

失败时 Doctype 为 `pts_rs_failure`：

| 场景 | 响应 |
|---|---|
| 未经验证就请求 API / 不支持的请求 | `<ErrorType>1</ErrorType><Key>213002</Key><FailureMessage>Invalid request string</FailureMessage>` |
| 权限错误（无 API Output 权限或 license 不足） | `<ErrorType>0</ErrorType><Key>9</Key>`（无 FailureMessage） |

## 七～十六：各分类请求/响应明细

以下条目由文档原文（12.2.x 各章）逐条提取，Tag 名保留原文（含拼写异常）。每条含：说明、触发事件、请求参数（Tag — 说明，Required）、响应父标签与主要字段。
`StartDateTime`/`EndDateTime` 语义同 1.3；`Event_Detail 的 name/value 对` 表示可把事件明细里的 NAME/VALUE 作为额外 Tag 精确过滤。

---

## 七、协议类 API（续：ProSchedule 起）

### ProSchedule（Protocol Schedule information）

- 说明：协议测量计划（Protocol Schedule）信息查询。协议计划修订事件发生后，调用方可用本 API 拉取受影响的测量计划；任意时刻可调，只读。
- 触发事件：New schedule；Edit/Delete schedule（ProSchedule event）。
- Event_Detail：
  - `MeasurementName`（Informational）
  - `PretestAnimalNumber`（Informational）
  - `PMEAPRO_ID`（主键，Edit_Type `½/3`＝1/2/3 标识动作）
  - `PROPHS_ID`（Informational）
- 请求参数（Tag — 说明，Required）：
  - `StudyName` — Colony/Study 名称（Y）
  - `MeasurementName` — 测量名（N）
  - `Types` — 类型索引，1=colony，2 或 null=study；缺省按 study（N）
  - `PMEAPRO_ID` — study/colony 协议测量过程 ID（N）
  - `ColonyID` — Colony 动物编号（N）
  - `ProPhaseID` — 协议阶段索引（N）
  - Event_Detail 的 name/value 对（N）
- 响应（父标签 `<ProScheduleInfo>`，另含子标签 `<ProScheduleDays>`、`<AnimScheduleInfo>`、`<AnimScheduleDays>`）：
  - ProtocolID — 协议主键
  - PmeaProID — 协议测量过程 ID
  - ProPhaseID — 协议阶段索引
  - PhaseName — 协议阶段名
  - ColonyID — Colony 动物编号
  - GraceDaysBefore / GraceDaysAfter — 计划日之前/之后允许的宽限天数
  - SOPReference — SOP 参考号
  - SchFreq / SchFreqName / SchFreqName Foreign — 计划频率索引/名称/外文名（如 1/day、n/day，n=NumOfSessions）
  - MeasurementType / MeasurementID / MeasurementName / MeasurementNameForeign — 测量类型、测量 ID、测量名、测量外文名
  - NumOfSessions — 计划中的 session 总数
  - SubSubclass / SubSubclassName / SubSubclassNameForeign — 受试子类（1=All Animals，2=All Males 等）及名称
  - 其余含 Generation、EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID 等
  - `<ProScheduleDays>`：Day（计划日索引）
  - `<AnimScheduleInfo>`：AnimalID、ColonyID
  - `<AnimScheduleDays>`：AnimalSchDay（原文 "schedule day foer an animal"）

### ProNecSchedule（Protocol Necropsy Schedule information）

- 说明：协议剖检计划信息查询；协议批准后剖检计划新增/修改/删除时按受影响计划调用，只读。
- 触发事件：New Necropsy schedule after the protocol approval；Edit/Delete Necropsy schedule after the protocol approval。
- Event_Detail：`PRONEC_ID`（主键，Edit_Type `½/3`＝1/2/3）、`PROPHS_ID`（Informational）。
- 请求参数（Tag — 说明，Required）：
  - `StudyName` — 专题名（Y）
  - `Types` — 1=colony，2 或 null=study；缺省按 study（N）
  - `PRONEC_ID` — study/colony 协议剖检计划 ID（原文注为 "protocol measurement process id"，N）
  - `ProPhaseID` — 协议阶段索引（N）
  - Event_Detail 的 name/value 对（N）
- 响应（原文写 Parent tag `<ProScheduleInfo>`——疑为笔误，实际应为剖检计划父标签；另含 `<ProMeasGrp>`）：
  - ProtocolID — 协议主键
  - PRONEC_ID — 协议剖检计划 ID
  - Name / ForeignName — 剖检名称/外文名
  - ProPhaseID / PhaseName / DayOfPhase — 协议阶段、阶段名、阶段日
  - GraceDaysBefore / GraceDaysAfter — 计划日前后宽限天数
  - TimeToSacrifice — 相对给药阶段起始日的计划剖检天数（15 页级长说明：P21D/P38D/P39D 等，随起始日标志不同而 ±1）
  - SubSubclass / SubSubclassName / SubSubclassNameForeign — 受试子类及名称
  - Generation / ScreenOrder — 代数 / 排屏顺序
  - SelectMethod / SelectMethod Name / SelectMethod NameForeign — 选择方法（1=First in group、2=Last in group 等）及名称
  - SkipUnschDead — 跳过非计划死亡 Y/N
  - 其余含 EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID 等
  - `<ProMeasGrp>`（受试子类为 Individual groups/Individual animals 时按死亡状态重复）：GroupNo、NumOfAnimals、Sex、SubGroupNumber

### ProParameter（Protocol Parameter information）

- 说明：取协议参数信息（参数名、缩写、单位、小数位等）；任意时刻可调，只读。
- 触发事件：无/未实现（文档未列事件触发器）。
- 请求参数（Tag — 说明，Required）：
  - `StudyName` — Colony/Study 名称（Y）
  - `Types` — 1=colony，2 或 null=study；缺省按 study（N）
  - `Generation` — 多代研究代数，单代为 0；缺省 0（N）
  - `ParamType` — 参数类型索引（N）
  - `ActiveOnly` — Y 时仅返回 Active 的数值型参数（N）
- 响应（父标签 `<ProParameterInfo>`）：
  - ProtocolID — 协议主键
  - StudyName — Colony/Study 名称
  - Generation — 代数
  - Types — 请求中的 Types
  - StorageUnit — 单位
  - PmeaProID — 测量计划 ID
  - MeasType — 测量类型索引
  - ParamType / ParamTypeName / ParamTypeNameForeign — 参数类型索引/名称/外文名
  - ParamName / ParamNameForeign / Abbreviation — 参数名/外文名/缩写
  - DisplayDecimal / DisplayUnit / ReportDecimal / ReportUnit — 显示小数位/显示单位/报告小数位/报告单位
  - 其余含 EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID 等
  - 注意：原文表中 `StorageUnit` 出现两次（第 5 行与第 12 行）。

### ProRelFinding（Protocol Relevant Finding information）

- 说明：取协议相关发现（protocol relevant finding）信息；签名锁定（signed off）后新增/修改/删除或 RFM 签名时触发，只读。
- 触发事件：New protocol relevant finding for a group/sex after signed off（PRO_REL_FINDING）；Edit/Delete protocol relevant finding for a group/sex signed off（PRO_REL_FINDING）；RFM sign off（此情形 Event_detail 中 `PRORFD` 为 null）（RFM_SIGNOFF）。
- Event_Detail：`PROREF_ID`（Protocol Identifier）、`MeasurementName`、`PARAM_TYPE`（Parameter type）（均为 Informational）、`PRORFD_ID`（主键，Edit_Type `½/3`）。
- Qualified fields：None。
- 请求参数（Tag — 说明，Required）：
  - `PROREF_ID` — 协议索引（Y）
  - `StudyName` — Colony/Study 名称（N）
  - `ParamType` — 参数类型索引（N）
  - `PRORFD_ID` — 协议相关发现索引（N）
  - `MeasurementName` — 一个或多个关注的测量名（N）
  - `SignOff` — Y 表示只关心已签名记录（N）
  - 注意：原文表 65 末尾有一空行（表格瑕疵）。
- 响应（父标签 `<ProRelFindingInfo>`）：
  - ProtocolID / StudyName / Generation / Types — 协议主键、名称、代数、类型
  - PRORFD_ID — 协议相关发现记录索引
  - GroupNumber / Sex — 组号 / 性别
  - ProPhsID / PhaseName / DayOfPhase / EndDayOfPhase / CombineDay / EndProPhsID / EndPhaseName — 起止阶段、阶段日、合并日（如 1-8）
  - DeathStatus — 剖检（sacrifice）名称
  - TreatmentFlag / TreatmentModifier / TreatmentComment — 处理标记/修饰/注释
  - ParamType / MeasurementName — 参数类型、测量名
  - TisOrCatOrParam — 大体/镜下观察时为组织名；临床体征时为类别名；广义测量时为参数名
  - FindingOrSubcat — 大体时为 finding 名，镜下时为 finding 长名，临床体征时为子类别
  - SeverityName / LocationName / DistributionName / RelToDeathName / RelToTreatName / SizeName — 各类修饰名
  - 其余含 Modifier_1Name…Modifier_6Name、Session、SessionName（计划剖检 session=101；Timed bleeding 且 measurement type=180 时 Session 号 +200）等

### StudyBaselineData（Study Baseline Data information）

- 说明：取专题基线数据（研究内基线）信息；基线条目新增/删除时触发，只读。
- 触发事件：New Study Baseline Data entered in STUDY_BASELINE_DATA；Delete Study Baseline Data in STUDY_BASELINE_DATA。
- Event_Detail（Qualified fields：None）：`PROREF_ID`、`STDBAS_ID`（主键）、`ANIMAL_ID`、`StudyAnimalNumber`、`PretestAnimalNumber`、`PMEAPRO_ID`、`MeasurementName`、`MeasurementType`、`SCHEDULED`、`SubjectID`、`SESSION_NUMBER`、`PROPHS_ID`、`PHASENAME`、`DAY_OF_PHASE`（除 STDBAS_ID 外均为 Informational）。
- 请求参数（Tag — 说明，Required）：
  - `PROREF_ID` — 协议索引（Y）
  - `StudyName` — 专题名（N）
  - `STDBAS_ID` — 基线数据记录索引（N）
  - `MeasurementName` — 一个或多个关注的测量名（N）
  - 注意：原文表 68 末尾有一空行。
- 响应（父标签 `<StudyBaselineData>`）：
  - ProtocolID — 协议主键
  - StudyName — Colony/Study 名称
  - Generation — 代数
  - STDBAS_ID — 基线数据记录索引
  - StudyAnimalNumber / PretestAnimalNumber — 专题动物号 / 检前动物号
  - ProPhsID / PhaseName / DayOfPhase — 协议阶段、阶段名、阶段日
  - SubjectID — 受试索引（1 – Animals，2 – Samples）
  - MeasurementName — 测量名
  - MeasurementType — 测量类型（101 – Body Weights；111 – Generalized Measurement）
  - Session — session 号（原文行尾多余括号，未闭合）
  - ScheduledFlag — S/U（计划/非计划 session）
  - REC_ID — 记录索引

---

## 八、动物信息类

### AnimalData（Study animal information）

- 说明：取 Colony/Study 动物数据（个体档案、分组、死亡、笼位、植入物、供应商等）；动物任何状态类事件触发，只读。
- 触发事件（13 项）：Create Permanent Colony/Study Animal Record；Change Colony Animals Subgroups；Mark Colony/Study Animal Dead；Mark Study Animal Complete；Assign Colony/Study Implants；Change Colony/Study Animal Status；Assign animal to phase；Assign animal to cage；Update animal characteristics；Return To Colony；Recover From Colony；Mark Colony/Study Animal Resurrected；Swap Group Assignment；Move Animal From Cage。
- Event_Detail：`PretestAnimalNumber`（Informational）、`PROREF_ID`（原文标 "Primary key for the record"，Edit_Type 空）、`ANIMAL_ID`（主键，Edit_Type `½/3`）。
- 请求参数（Tag — 说明，Required）：
  - `StudyName` — 专题或 colony 名（Y）
  - `ProtocolID` — 协议索引（Y）
  - `Types` — 1=colony，2 或 null=study；缺省按 study（N）
  - `ANIMAL_ID` — 动物索引（N）
  - `PretestAnimalNumber` — 检前动物号（N）
  - `ColonyID` — Colony 动物号（N）
  - `Generation` — 多代研究代数，单代 0；缺省 0（N）
  - `StudyAnimalOnly` — Y 表示只关心专题动物，不含检前动物（N）
  - `IncludeComplete` — Y 表示纳入未死亡但已标记 complete 的动物的完成日期信息（原文 Required 列为 Y）
- 响应（父标签 `<AnimalInfo>`）：
  - ProtocolID / StudyName / Generation / NumGeneration / Types / ReproStudyFlag — 协议主键、名称、代数、代数数量、类型、是否有妊娠阶段
  - AnimalID / StudyAnimalID / StudyAnimalNumber / PretestAnimalNumber / ColonyID — 动物标识组
  - EarliestStartDate — 动物在各阶段的最早开始日期
  - `*RefStartDate` — 参考开始日期（脚注：取最早的 Dosing 阶段开始日；无 Dosing 则取 Randomization 阶段；再无则取第一个非 pretest 阶段；再无则取 pretest 阶段）
  - LastDoseDateTime / FirstDoseDateTime — 最后/首次给药（或部分给药）时间，**不含 Pretest 阶段给药**
  - ReceiptDate / OrderNumber — Colony 动物接收日期/订单号
  - GroupNumber / SubGroupNumber / ColonySubgroupID / ColonySubgroupName / ColonySubgroupForeignName — 分组信息
  - OnStudy — Y=在专题内，null/N=在 colony
  - OrigColonyName / TransferStatusIndex / TransferStatusText / TransferStatusForeignText / CurrentLocation — 来源 colony、转移状态、当前位置
  - DrugNaive / DoseNaive — 药物/给药 naïve 标记
  - DeathStatusCode / DeathStatusRefID / DeathStatusID / StudyDeathStatusID / DeathStatus / DeathType / Scheduled / ScheduledFlag / DeathStatusForeign / DeathProPhaseID / DeathPhase / DeathPhaseForeign / NecSchDayOfPhase / DayOfPhase / DeathTime / Approximate / DeathEntryDateTime / DeathEntryOperator / DeathEntryOperatorID / DeathEntryOperatorRefID — 死亡/完成信息（NecSchDayOfPhase 为计划日，DayOfPhase 为实际日）
  - 其余含 ImplantAssignmentID、ImplantNumber、Sex、SpeciesRefID、StrainID、StrainRefID、StrainName、StrainNameForeign、MultiSupplier、SupplierID、SupplierRefID、SupplierLocation、SupplierName、SupplierCode、DamParturitionDate、ParturitionDate、Tattoo、LabID、AgeRefDate、AgeUnit、AgeSignificance、ReferenceAge、AWACategory、EstWeight、Dam、Sire、Litter、Color、Markings、AUPNumber、Investigator、Comments 等

### AnimalPhase（Study Animal Phase Assignment information）

- ⚠️ **Category 名大小写敏感（实测）**：现网要用 `AnimalPhase`；
  文档章节标题里的 `StudyAnimalPhase` 被服务端拒（`Key=214002`）。

- 说明：取动物阶段分配（phase assignment）信息；任意时刻可调，只读。
- 触发事件：Assign animal to any phase；Edit animal phase assignment；Delete animal phase assignment。
- Event_Detail：`PretestAnimalNumber`、`GENERATION`、`TYPES`、`ANIMAL_ID`（均 Informational）、`PHSASN_ID`（主键，Edit_Type `½/3`）。
- 请求参数（Tag — 说明，Required）：原文给出**两张**请求表（表 74、表 75），合并如下：
  - `StudyName` — 专题或 colony 名（Y）
  - `Types` — 1=colony，2 或 null=study；缺省按 study（N）
  - `ANIMAL_ID` — 动物索引（N）
  - `PHSASN_ID` — 动物阶段分配索引（N；表 75 附注：若请求不含此 tag，则不返回 EditFlag/DeleteFlag；同一记录多次编辑只取最新一条；记录已删除时若不含此 tag 则不返回）
  - `Generation` — 多代研究代数，单代 0；缺省 0（N）
  - `StudyAnimalNumber` — 专题动物号（N）
  - `PretestAnimalNumber` — 检前动物号（N）
- 响应（父标签 `<AnimalPhaseInfo>`）：
  - ProtocolID / NumGeneration — 协议主键、代数数量
  - `#StudyName` / `#Generation` / `#Types` — 交替键字段（见脚注）
  - PHSASN_ID — 动物阶段分配索引
  - `#AnimalID` / StudyAnimalID / `#StudyAnimalNumber` / `#PretestAnimalNumber` / `#ColonyID` — 动物标识
  - PhaseName / PhaseNameForeign / FootNote — 阶段名/外文名/脚注符号
  - `#ProPhsID` / `#PhaseType` / PhaseTypeName / PhaseTypeNameForeign — 协议阶段与阶段类型
  - AnimalStartDate / CageNumber — 动物进入该阶段日期、该阶段笼号
  - EntryDateTime / EntryOperator / EntryOperatorID / EntryOperatorRefID — 录入信息（EntryOperatorID 原文类型写作 Character string）
  - DeleteFlag / EditFlag — 删除/编辑标记
  - 脚注 `#`：记录的交替键；若 DeleteFlag=Y，除主键外，交替键中非空的列也需返回。

### AnimalCage（Study Animal Cage Assignment information）

- 说明：取动物笼位分配信息；任意时刻可调，只读。
- 触发事件：无/未实现（文档未列事件触发器）。
- 请求参数（Tag — 说明，Required）：
  - `Types` — 1=colony，2 或 null=study；缺省按 study（N）
  - `StudyName` — 专题名（Y）
  - `Generation` — 多代研究代数，单代 0；缺省 0（N）
  - `CageNumber` — 该阶段分配的笼号（N）
  - `StudyAnimalNumber` — 专题动物号（N）
  - `PretestAnimalNumber` — 检前动物号（N）
- 响应（父标签：顶层为 ProtocolID/StudyName/Generation/Types；每条笼位记录在 `<AnimalCageInfo>` 内）：
  - ProtocolID / StudyName / Generation / Types — 顶层字段
  - AnimalID / StudyAnimalID / StudyAnimalNumber / PretestAnimalNumber — 动物标识
  - PhaseName / PhaseNameForeign / ProPhaseID — 阶段信息
  - CageMethod / CageMethodName / CageMethodNameForeign — 笼养方式
  - CageNumber / DateCaged / DateRemoved — 笼号、入笼时间、出笼时间
  - EntryDateTime / EntryOperator / EntryOperatorID / EntryOperatorRefID — 录入信息
  - 注意：本 API 响应节标题原文写作 "Animal phase assignment data in XML format"（复制粘贴笔误，实为笼位数据）。

---

## 九、In-life / 临床病理类

### BodyWeight（Body Weights）

- 说明：取体重数据（可含参数明细）；体重数据新增/编辑/删除时触发，只读。
- 触发事件：New body weight data for an animal；Edit/Delete body weight data for an animal。
- Qualified fields（限定字段）：`WEIGHT_TAKEN`（Y=Weight is taken / N=Not taken）。
- Event_Detail：`PROREF_ID`（Protocol Identifier）、`WEIGHT_TAKEN`（限定字段）、`MeasurementName`、`PretestAnimalNumber`、`GENERATION`、`TYPES`（均 Informational）、`BodyWeightType`（Informational，Edit_Type 列注 1 – Live Body Weight / 2 – Terminal Body Weight）、`BW_ID`（主键，Edit_Type `½/3`）。
- 请求参数（Tag — 说明，Required）：
  - `StartDateTime` — 该时间之后（含）录入/修改/删除的数据（N）
  - `EndDateTime` — 该时间之前（不含）录入/修改/删除的数据（N）
  - `MeasurementName` — 一个或多个关注的测量名（N）
  - `StudyName` — 专题或 colony 名（Y）
  - `ProtocolID` — 协议索引（Y）
  - `Generation` — 多代研究代数，单代 0；缺省 0（N）
  - `StudyAnimalNumber` / `PretestAnimalNumber` / `ColonyID` — 动物标识（N）
  - `BW_ID` — 体重记录索引（N）
  - `WeightTaken` — Y 表示只关心已称重数据（N）
  - `IncludeParameter` — Y 表示同时返回体重参数数据（N）
  - `GroupNumber` — 一个或多个关注组号（N）
  - `ProPhsID` / `PhaseName` — 协议阶段（N）
  - `StudyAnimalOnly` — Y 只关心专题动物（N）
  - `LatestDataOnly` — Y 只取最新数据，不返回 EditFlag/DeleteFlag；多次编辑只取最新一条（限 StartDateTime/EndDateTime 区间内）；已删除记录不返回（N）
  - `CountOnly` — Y 只关心数据条数（N）
  - `Types` — 1=colony，2 或 null=study；缺省按 study（N）
  - `StudyDataFlag` — 参见 CellMorphology API 对该请求参数的说明（N）
  - `N` — 请求的最大记录数（N）
  - Event_Detail 的 name/value 对（N）
- 响应（父标签 `<BodyWeightInfo>`）：
  - 顶层：`#StudyName`、`#Generation`、`#Types`、`Count`（按测量名计数）
  - MeasurementNameForeign / MeasurementName — 测量外文名/测量名
  - BodyWeightID — 体重记录索引
  - BodyWeightType — 1 – Live Body Weight adult；2 – Terminal Body Weight；3 – Pup Body Weight
  - WeightTaken / NotTakenReason — 是否称重 / 未称重原因
  - RawWeight / StorageUnit — 实际体重值 / 单位
  - `*ParamName` / `*ParamNameForeign` / `*Abbreviation` / `*DisplayDecimal` / `*DisplayUnit` / `*ReportDecimal` / `*ReportUnit` — 参数明细（仅 `IncludeParameter=Y` 时返回）
  - Exclude / ExcludeReason / BLFlag / Fasting / FastingDesc / ColonyFlag — 排除标记、基线标记、禁食标记、colony 关联标记
  - `#DateTaken` / CageNumber / GroupNumber / SubGroupNumber / ColonySubgroupName / ColonySubgroupForeignName
  - 其余含 SignUserID、SignUserName、SignDateTime、SignMeaning、ProPhsID、PhaseType、PmeaProID、DayOfPhase、`#Session`、SessionName、SessionNameForeign、`#ScheduledFlag`、RealTime、EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、EntryMethodID、`#AnimalID`、EntryMethodName、EntryMethodNameForeign、`#StudyAnimalNumber`、`#PretestAnimalNumber`、`#ColonyID`、Comments、DeleteFlag、EditFlag 等
  - 脚注 `*`：仅当请求 `IncludeParameter=Y` 时可用。
  - 脚注 `#`：交替键；DeleteFlag=Y 时除主键（BodyWeightID）外，交替键中非空列也要返回。

### StudySampleResult（Approved to study sample data）

- 说明：取已批准入专题/colony 的样本结果（含细胞计数结果）；批准或样本广义数据编辑/删除时触发，只读。
- 触发事件：
  - Clinical Pathology：Initial reviewer approved sample results including cell count results to study（supervisory approval flag 关闭时）；Supervisor approved sample results（supervisory approval flag 打开时）。
  - Animal room Edit mode：Edit/delete of sample generalized data。
- Event_Detail：`MeasurementName`、`PretestAnimalNumber`、`SampleTubeID`、`GENERATION`、`TYPES`（均 Informational）、`GENDAT_ID`（主键，Edit_Type `½/3`）。
- 请求参数（Tag — 说明，Required）：
  - `StartDateTime` / `EndDateTime` — 时间窗（含/不含）（N）
  - `MeasurementName` — 一个或多个关注的测量名（N）
  - `PmeaProID` — 样本采集测量过程 ID（N）
  - `StudyName` — 专题或 colony 名（Y）
  - `Generation` — 代数（**原文该行 Required 列被说明文字 "The generation number" 占用，表格错位**）
  - `StudyAnimalNumber` / `PretestAnimalNumber` / `ColonyID` — 动物标识（N）
  - `SampleTubeID` — 样本管条码（N）
  - `GENDAT_ID` — 样本数据（广义数据）索引（N）
  - `NumericalOnly` — Y 只关心数值型参数（N）
  - `GroupNumber` / `ProPhsID` / `PhaseName` — 组号/阶段（N）
  - `CountOnly` — Y 只关心条数（N）
  - `Types` — 1=colony，2 或 null=study（N）
  - `StudyDataFlag` — 参见 CellMorphology API 说明（N）
  - `N` — 最大记录数（N）
  - Event_Detail 的 name/value 对（可含 GenDatID、MeasurementName、PretestAnimalNumber 及其值）（N）
- 响应（**原文未标注父标签名**，仅写 "Response- Generalized data in XML format"；顶层字段如下，每条记录字段同下）：
  - 顶层：`#StudyName`、`#Generation`、`#Types`、`Count`（按测量名计数）
  - MeasurementNameForeign / MeasurementName — 测量外文名/测量名
  - `#MeaDat_ID` / GenDatID — 测量数据索引 / 样本广义数据索引
  - `#SampleTubeID` / SampleRefID / SampleTubeKey — 样本管条码、样本参考索引、样本管标识索引
  - ProParamID / `#ParamID` / Abbreviation / `#ParamName` / ParamNameForeign / ParamType / ParamUnits / ParamDataType — 参数标识与主数据
  - DisplayDecimal / DisplayUnit / ReportDecimal / ReportUnit — 显示/报告小数位与单位
  - Exclude / ExclusionReason / BLFlag / ColonyFlag — 排除、基线、colony 关联标记
  - TextValue / TextName / TextNameForeign / NumericValue / DateTime — 结果值（文本/数值/日期）
  - RefRangeStatus / RefRangeStatusName / RefRangeStatusNameForeign / RefRangeHigh / RefRangeLow — 参考范围
  - 其余含 CodedComment、`#InstrumentID`、Comment、InstrumentName、AnaSmpTypeID、AnaSmpTypName、AnaSmpTypNameForeign、`#DateTaken`、SiteID、SiteName、CageNumber、GroupNumber、SubGroupNumber、ColonySubgroupName、ColonySubgroupForeignName、SignUserID、SignUserName、SignDateTime、SignMeaning、ProPhsID、PmeaProID、DayOfPhase、`#Session`、`#SessionName`、SessionNameForeign、ScheduledFlag、RealTime、EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、EntryMethodID、`#AnimalID`、EntryMethodName、EntryMethodNameForeign、`#StudyAnimalNumber`、`#PretestAnimalNumber`、`#ColonyID`、DeleteFlag、EditFlag 等
  - 脚注 `#`：DeleteFlag=Y 时除主键（GenDatID）外，交替键中非空列也要返回。

### SampleCollection（Sample Collection）

- 说明：取样本采集数据（含每管明细与分装管明细）；动物房/剖检或临床病理环节的采集、收样、流转、复核事件触发，只读。
- 触发事件（新增/编辑）：Animal room 或 Necropsy 中新增/编辑样本采集数据；Clinical Pathology 中在 Sample receipt、sample tracking、sample review、sample supervisor review 录入/编辑样本明细。
- 触发事件（删除，**独立事件，Event_Detail 另有一张表**）：Animal room 或 Necropsy 中删除样本采集数据；Clinical Pathology 中在四个环节删除样本明细。
- Event_Detail（新增/编辑）：`STATUS`（限定字段，1 – collected，99 – not collected）、`MeasurementName`、`PretestAnimalNumber`、`SampleTubeID`、`GENERATION`、`TYPES`（均 Informational）、`SupervisoryReview`（限定字段，Y/N）、`STBCDT_ID`（主键，Edit_Type `½/3`）。
- Event_Detail（删除）：同上，另加 `SampleTubeKey`、`AnaSmpTypeID`、`AnaSmpTypName`、`DateTaken`、`SessionName`、`MeaDat_ID`、`CollectVolumeParamID`（均 Informational）。
- 请求参数（Tag — 说明，Required）：
  - `StartDateTime` / `EndDateTime` — 时间窗（含/不含）（N）
  - `MeasurementName` — 一个或多个关注测量名（N）
  - `MeasurementType` — 测量类型索引（N）
  - `PmeaProID` — 样本采集测量过程 ID（N）
  - `StudyName` — 专题或 colony 名（Y）
  - `Generation` — 代数（**原文 Required 列被说明文字占用，表格错位**）
  - `StudyAnimalNumber` / `PretestAnimalNumber` / `ColonyID` — 动物标识（N）
  - `SampleTubeID` — 样本管条码（N）
  - `SampleCollectDataID` — 样本采集数据索引（N）
  - `STBCDT_ID` — 样本管采集数据索引（N）
  - `Status` — 0/null=全部；1=仅已采集；99=仅未采集（N）
  - `GroupNumber` / `ProPhsID` / `PhaseName` — 组号/阶段（N）
  - `CountOnly` — Y 只关心条数（N）
  - `Types` — 1=colony，2 或 null=study（N）
  - `N` — 最大记录数（N）
  - Event_Detail 的 name/value 对（例如 SampleTubeID 及取值，定位某一管）（N）
- 响应（父标签 `<SampleCollData>`；每管子标签 `<SampleTubeCollData>`；每分装管子标签 `<SampleTubeAliquotData>`）：
  - 顶层：`#StudyName`、`#Generation`、`#Types`、`Count`（按测量名计数）
  - MeasurementNameForeign / MeaDat_ID / MeasurementName / SmpCollDataID — 测量与采集数据标识
  - StatusID / StatusName / StatusNameForeign — 采集状态（1 – collected，99 – not collected）
  - Type / TypeName / TypeNameForeign — 采集发生的环节（1 – Animal room；2 – Necropsy；3 – Sample receipt；4 – Sample review；5 – Sample supervisor review）
  - CollectionSiteID / CollectionSiteName / CollectionSiteNameForeign — 采集部位
  - SmpCondID / SmpCondName / SmpCondName Foreign — 样本状态/条件（原文名称含空格）
  - Fasted / FastedTime / Fasting / FastingDesc / NoWater / NoWaterTime / UrineCollectTime — 禁食禁水与收尿时长
  - AnesthesiaTypeID / AnesthesiaTypeName / AnesthesiaTypeNameForeign / NotTakenReason — 麻醉与未采集原因
  - `#DateTaken` / CageNumber / GroupNumber / SubGroupNumber / ColonySubgroupName / ColonySubgroupForeignName
  - 其余含 SignUserID、SignUserName、SignDateTime、SignMeaning、SampleRefID、CollectionSampTypeID、CollectionSampTypeName、CollectionSampTypeNameForeign、ProPhsID、PmeaProID、DayOfPhase、`#Session`、`#SessionName`、SessionNameForeign、TimePointRefText、ElapseTime、TimePointText、DateTimeOfDose、ScheduledFlag、RealTime、EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、EntryMethodID、`#AnimalID`、EntryMethodName、EntryMethodNameForeign、`#StudyAnimalNumber`、`#PretestAnimalNumber`、`#ColonyID`、`**DeleteFlag`、`**EditFlag` 等
  - `<SampleTubeCollData>`（每管）：SampleTubeID、SampleTubeKey、Status、StatusName、StatusNameForeign、CollectVolumeParamID、CollectVolume、VolumeUnit、CollectWeight、CollectWeightUnits、ReqVolume、ReqVolumeUnit、LotNumber、Manufacturer、LotExpirationDate、Comments、DateTaken、Session、SessionName、SessionNameForeign、TimePostDose、AnaSmpTypeID、AnaSmpTypName、AnaSmpTypNameForeign、CollectionSiteID、CollectionSiteName、CollectionSiteNameForeign、AnaMeasName、NotTakenReason、RealTime、EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、EntryMethodID（1- Key entry；2 – Online；3 – calculated）、EntryMethodName、EntryMethodNameForeign
  - `<SampleTubeAliquotData>`（每分装管，源自 SAMPLE_TUBE_IDENTIFICATION，SMTBID_ID_ORIGINAL 指向采集管）：SampleTubeID、SampleTubeKey、AliquotID、AnalysisVolume、AnalysisVolumeUnit、AnaMeasName、AnaSmpTypName
  - 脚注 `**`（EditFlag/DeleteFlag 逻辑）：对 sample_collect_data 的插入/更新与对 sample_tube_collect_data 的插入/更新/删除且**无审计**＝insert（两个 tag 均为 null）；对 sample_collect_data 带审计更新，或对管表带审计插入/更新/删除＝update（返回 `<EditFlag>Y</EditFlag>`）；对 sample_collect_data 带审计删除＝delete（返回 `<DeleteFlag>Y</DeleteFlag>`）；不带审计删除则不返回记录；不会为每个 `<SampleTubeCollData>` 单独发 EditFlag/DeleteFlag。
  - 脚注 `#`：DeleteFlag=Y 时除主键外，交替键中非空列也要返回。

### GenMeas（Generalized animal data）

- 说明：取动物广义测量（generalized measurement）数据；动物房新增/编辑/删除时触发，只读。
- 触发事件：In Animal room：New generalized measurement animal data；Edit/delete of generalized measurement animal data。
- Event_Detail：`MeasurementName`、`PretestAnimalNumber`、`MeasurementName`（**原文重复出现两次**）、`GENERATION`、`TYPES`、`GENDAT_ID`（主键，Edit_Type `½/3`）。
- 请求参数（Tag — 说明，Required）：
  - `StartDateTime` / `EndDateTime` — 时间窗（含/不含）（N）
  - `MeasurementName` — 一个或多个关注测量名（N）
  - `PmeaProID` — 广义测量过程 ID（N）
  - `StudyName` — 专题或 colony 名（Y）
  - `GroupNumber` / `ProPhsID` / `PhaseName` — 组号/阶段（N）
  - `StudyAnimalNumber` / `PretestAnimalNumber` / `ColonyID` — 动物标识（N）
  - `GENDAT_ID` — 广义数据索引（N）
  - `NumericalOnly` — Y 只关心数值型参数（N）
  - `CountOnly` — Y 只关心条数（N）
  - `Types` — 1=colony，2 或 null=study（N）
  - `StudyDataFlag` — 参见 CellMorphology API 说明（N）
  - `IncludeSchedule` — Y 返回该测量的计划日，N/null 不返回，默认 N（N）
  - `N` — 最大记录数（N）
  - Event_Detail 的 name/value 对（可含 GenDatID、PretestAnimalNumber 及其值）（N）
- 响应（父标签 `<ParamDataInfo>`）：
  - 顶层：StudyName、Generation、MeasurementName、Count（按测量名计数）、ScheduledDays（该测量的计划日）
  - MeasurementNameForeign / GenDatID / ProParamID / ParamID / Abbreviation / ParamName / ParamNameForeign / ParamType / ParamUnits / ParamDataType — 测量与参数标识
  - DisplayDecimal / DisplayUnit / ReportDecimal / ReportUnit — 显示/报告小数位与单位
  - ValueTaken / NotTakenReason / Exclude / ExclusionReason — 取值/排除标记
  - TextValue / TextName / TextNameForeign / NumericValue / DateTime — 结果值
  - RefRangeStatus / RefRangeStatusName / RefRangeStatusNameForeign / RefRangeHigh / RefRangeLow — 参考范围
  - DateTaken / TimeTaken — 取数日期（优先 generalized_data_details.date_data_taken，其次 GEN_MEAS_SESSION_DETAILS.date_time_taken，再次 generalized_data.date_data_taken）/ 时间部分（HH:MM:SS）
  - 其余含 CageNumber、GroupNumber、SubGroupNumber、ColonySubgroupName、ColonySubgroupForeignName、SignUserID、SignUserName、SignDateTime、SignMeaning、ProPhsID、PmeaProID、DayOfPhase、Session、SessionName、SessionNameForeign、ScheduledFlag、RealTime、EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、EntryMethodID、AnimalID、EntryMethodName、EntryMethodNameForeign、StudyAnimalNumber、PretestAnimalNumber、ColonyID、Comment、TimePointRefText、ElapseTime、DateTimeOfDose、Position、Method、Lead、Cstate、BLFlag、ColonyFlag、EndDateTaken、DeleteFlag、EditFlag 等

### NonAnimalMeas（Non-Animal Generalized Measurement）

- 说明：取非动物广义测量数据（如环境/饲料等非动物对象）；动物房新增/编辑/删除时触发，只读。
- 触发事件：In Animal room：New generalized measurement non-animal data；Edit/delete of generalized measurement non-animal data。
- Event_Detail：`MeasurementName`、`GENDAT_ID`（主键，Edit_Type `½/3`）、`GENERATION`、`TYPES`。
- 请求参数（Tag — 说明，Required）：
  - `StartDateTime` / `EndDateTime` — 时间窗（含/不含）（N）
  - `MeasurementName` — 一个或多个关注测量名（N）
  - `PmeaProID` — 非动物广义测量过程 ID（N）
  - `StudyName` — 专题或 colony 名（Y）
  - `GENDAT_ID` — 广义数据索引（N）
  - `NumericalOnly` — Y 只关心数值型参数（N）
  - `Types` — 1=colony，2 或 null=study（N）
  - `CountOnly` — Y 只关心条数（N）
  - `N` — 最大记录数（N）
- 响应（父标签 `<ParamDataInfo>`）：
  - 顶层：MeasurementName（非动物广义数据的测量名）、Count
  - MeasurementNameForeign / GenDatID / ProParamID / ParamID / Abbreviation / ParamName / ParamNameForeign / ParamType / ParamUnits / ParamDataType — 测量与参数标识
  - DisplayDecimal / DisplayUnit / ReportDecimal / ReportUnit / Exclude / ExclusionReason — 显示与排除
  - TextValue / TextName / TextNameForeign / NumericValue / DateTime / DateTaken — 结果值
  - 其余含 SignUserID、SignUserName、SignDateTime、SignMeaning、ProPhsID、PmeaProID、DayOfPhase、Session、SessionName、SessionNameForeign、ScheduledFlag、RealTime、EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、EntryMethodID、NonAnimCatItemID、NonAnimCatItemName、NonAnimCatItemNameForeign、EntryMethodName、EntryMethodNameForeign、Comments、DeleteFlag、EditFlag 等

### QCSampleResult（Approved QC（Quality Control）sample results data）

- 说明：取 QC 样本质控结果（含已批准/未批准数据与错误标记）；临床病理首次复核或主管复核批准 QC 结果时触发，只读。
- 触发事件：In Clinical Pathology：Initial reviewer approved quality control sample results to the instrument（supervisory approval flag 关闭时）；Supervisor approved quality control sample results（supervisory approval flag 打开时）。
- Event_Detail：`STATUS`（accepted/rejected/excluded 状态，Informational）、`QCSPRS_ID`（主键，Edit_Type `½/3`）、`LevelSampleID`（Informational）。
- 请求参数（Tag — 说明，Required）：
  - `StartDateTime` / `EndDateTime` — 时间窗（含/不含）（N）
  - `LevelID` — QC 样本水平标识（N）
  - `LevelSampleID` — QC 水平样本管条码（N）
  - `QCSPRS_ID` — QC 样本结果数据索引（N）
  - `NumericalOnly` — Y 只关心数值型参数（N）
  - `CountOnly` — Y 只关心条数（N）
  - `N` — 最大记录数（N）
  - Event_Detail 的 name/value 对（可含 QCSampleResultID（QCSPRS_ID）、LevelSampleID 及其值）（N）
- 响应（父标签 `<QCSampleResultInfo>`）：
  - Count — QC 样本结果记录数
  - QCSampleResultID / QCLevelID / LevelID / LevelName / LevelNameForeign / LevelSampleID — QC 结果与水平信息
  - ResultValue / RunNumber — 结果值 / run 号
  - ParamID / Abbreviation / ParamName / ParamNameForeign / ParamType / ParamUnits / ParamDataType — 参数标识
  - SampleStatusIndex / SampleStatusText / SampleStatusForeignText / LastSavedStatusIndex / LastSavedStatusText / LastSavedStatusForeignText — 样本状态与上次保存状态
  - RuleID / RuleName / RuleForeignName / RuleNotation / RuleStatusIndex / RuleStatusText / RuleStatusForeignText — QC 规则信息
  - LinRangeStatusIndex / LinRangeStatusText / LinRangeStatusForeignText — 线性范围状态
  - CupID / PlateID / SequenceID / DisplayDecimal / DisplayUnit / DateTime / Comments / ErrorCode — 仪器标识与结果展示
  - 其余含 InstrumentID、InstrumentName、DateTaken、DateTimeAnalyzed、DateTimeReviewed、DateTimeSupReviewed、OperatorID、OperatorName、ReviewerID、ReviewerName、SuprvisorID、SupervisorName、SiteID、SiteName、SignUserID、SignUserName、SignDateTime、SignMeaning、EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、EntryMethodID、EntryMethodName、EntryMethodNameForeign 等

### Memo（Animal and Colony log book）

- 说明：取动物/colony 日志本（log book）数据；日志录入或编辑/删除时触发，只读。
- 触发事件：New log book data for an animal and/or a colony is entered；Edit/Delete log book for an animal and/or a colony。
- Event_Detail：`PretestAnimalNumber`、`MEMODT_ID`（主键，Edit_Type `½/3`）、`GENERATION`、`TYPES`。
- 请求参数（Tag — 说明，Required）：
  - `StartDateTime` / `EndDateTime` — 时间窗（含/不含）（N）
  - `StudyName` — 专题或 colony 名（Y）
  - `Generation` — 多代研究代数，单代 0；缺省 0（N）
  - `ColonyID` — Colony 动物号（N）
  - `MEMODT_ID` — 日志记录索引（N）
  - `CountOnly` — Y 只关心条数（N）
  - `Types` — 1=colony，2 或 null=study（N）
  - `N` — 最大记录数（N）
  - Event_Detail 的 name/value 对（N）
- 响应（父标签 `<MemoInfo>`）：
  - Count — 按专题名的日志记录数
  - MemoDataID / ProtocolID — 日志记录索引 / 协议主键
  - SignUserID / SignUserName / SignDateTime / SignMeaning — 签名信息
  - DateTaken / MemoType / MemoLog — 取数时间、日志类型、日志内容
  - RealTime / EntryDateTime / EntryOperator / EntryOperatorID / EntryOperatorRefID / EntryMethodID / EntryMethodName — 录入信息
  - AnimalID / StudyAnimalNumber / PretestAnimalNumber / ColonyID — 动物标识
  - EditFlag / ForAnimal — 编辑标记 / 是否针对动物

### SampleDrawlist（Sample Collection Plan（Sample Drawlist））

- ⚠️ **Category 名大小写敏感（实测）**：现网要用 `SampleDrawlist`（小写 l）；
  `SampleDrawList` 被服务端拒（`Key=214002`）。

- 说明：取样本采集计划（drawlist，含分析面板参数）；colony/study 生成抽血单或增删动物时触发，只读。
- 触发事件：New drawlist generated for a Colony/Study；Edit/Delete Animals in the drawlist for the Colony/Study。
- Event_Detail：`MeasurementName`、`Types`（写明 1=colony，2 或 null=study）、`DRWLST_ID`（主键，Edit_Type `½/3`）。
- 请求参数（Tag — 说明，Required）：
  - `StartDateTime` — 样本采集开始日（含）（N）
  - `EndDateTime` — 样本采集结束日（不含，用于日期区间）（N）
  - `MeasurementName` — 关注的测量名（N）
  - `PmeaProID` — 样本采集测量过程 ID（N）
  - `StudyName` — 专题或 colony 名（Y）
  - `DRWLST_ID` — drawlist 数据索引（N）
  - `Types` — 1=colony，2 或 null=study（N）
  - Event_Detail 的 name/value 对（例如 DrawListID 及取值）（N）
- 响应（父标签 `<DrawListInfo>`；观察项子标签 `<PanelMeasParamInfo>`）：
  - DrawListID / NumberAnimals / NumberTubes — drawlist 索引、动物数、管数
  - ProPhsID / PmeaProID — 协议阶段、样本采集测量过程
  - SampleCollectMeasName / SampleCollectMeasNameForeign — drawlist 样本采集测量名/外文名
  - CollectionSampTypeID / CollectionSampTypeName / CollectionSampTypeNameForeign — 采集样本类型
  - SampleCollectionDate / ScheduledFlag / Generation — 采集日期、计划标记、代数
  - AnalysisPanelID / AnalysisPanelName / AnalysisPanelNameForeign — 分析面板
  - EntryDateTime / EntryOperator / EntryOperatorID / EntryOperatorRefID — 录入信息
  - `<PanelMeasParamInfo>`（每个观察项重复）：PanelMeasParamID、MeasurementID、MeasurementName、MeasurementNameForeign、MeasParamID、ParamID、Abbreviation、ParamName、ParamNameForeign

### SampleRef（Sample Reference）

- 说明：取样本参考（每根采血管的归属、类型、动物、体积等）数据；drawlist 生成或增删动物时触发，只读。
- 触发事件：New drawlist generated for a Colony/Study；Edit/Delete Animals in the drawlist for the Colony/Study。
- Event_Detail：`MeasurementName`、`Types`、`DRWLST_ID`（主键，Edit_Type `½/3`）。
- 请求参数（Tag — 说明，Required）：与 SampleDrawlist **完全相同**（StartDateTime、EndDateTime、MeasurementName、PmeaProID、StudyName(Y)、DRWLST_ID、Types、Event_Detail name/value 对）。
- 响应（父标签 `<DrawListInfo>`；管子标签 `<TubeInfo>`）：
  - 顶层与 SampleDrawlist 相同的 drawlist 字段（DrawListID、NumberAnimals、NumberTubes、ProPhsID、PmeaProID、SampleCollectMeasName(Foreign)、CollectionSampTypeID/Name/NameForeign、SampleCollectionDate、ScheduledFlag、Generation、AnalysisPanelID/Name/NameForeign、EntryDateTime/EntryOperator/EntryOperatorID/EntryOperatorRefID）
  - `<TubeInfo>`（每管重复）：SampleTubeKey、SampleRefID、SampleTubeID、TubeNumber、TubeTypeID、TubeTypeName、TubeTypeNameForeign、AnimalID、StudyAnimalNumber、PretestAnimalNumber、ColonyID、Sex、GroupNumber、SubGroupNumber、CageNumber、Volume、Unit、DayOfPhase、Session、SessionName、SessionNameForeign、AnaSmpTypeID、AnaSmpTypName、AnaSmpTypNameForeign、AnalysisMeasName、AnalysisMeasNameForeign、CollectionSiteID、CollectionSiteName、CollectionSiteNameForeign

### SampleTrack（Sample Tracking）

- 说明：取样本流转/状态跟踪数据（位置、状态、状态时间等）；样本采集、收样、处置、复核、批准时触发，只读。
- 触发事件：Sample collection, receipt, disposal, review and approval；In Clinical Pathology：Sample status and location 在 sample receipt、review、supervisor review 中录入/编辑/删除。
- Event_Detail：`½STATUS`（原文如此，实为 `STATUS`；限定字段，取值列写 `½/3/4/5/10/11` 即 1/3/4/5/10/11）、`PretestAnimalNumber`、`SMPTRK_ID`（主键，Edit_Type `½/3`）、`GENERATION`、`TYPES`。
- 请求参数（Tag — 说明，Required）：
  - `StartDateTime` / `EndDateTime` — 时间窗（含/不含）（N）
  - `StudyName` — 专题或 colony 名（Y）
  - `Types` — 1=colony，2 或 null=study（N）
  - `SMPTRK_ID` — 样本跟踪数据索引（N）
  - `SampleTubeID` — 样本管条码（N）
  - `N` — 最大记录数（N）
- 响应（父标签 `<SampleTrackingInfo>`）：
  - Count — 样本跟踪记录数
  - SampleTrackID / LocationID / LocationName / LocationNameForeign — 跟踪记录与样本位置
  - SampleTubeKey / SampleTubeID — 样本管
  - AnimalID / StudyAnimalNumber / PretestAnimalNumber / ColonyID — 动物标识
  - ProtocolID / StudyName / SampleCollectMeasName / SampleCollectMeasNameForeign — 协议与采集测量
  - CollectStatusID / CollectStatusName / CollectStatusNameForeign / CollectDate — 采集状态与采集时间
  - SampleTrackStatusIndex / SampleTrackStatus / SampleTrackStatusForeign / SampleTrackStatusDate — 跟踪状态（Received、Disposed 等）与状态时间
  - 其余含 Comments、SignUserID、SignUserName、SignDateTime、SignMeaning、EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID 等

### SampleObs（Sample Observation）

- 说明：取样本观察（样本异常/描述符）数据；采集、收样、复核、流转环节录入/编辑/删除样本观察时触发，只读。
- 触发事件：In Animal room 或 Necropsy：Sample observation entered/edited/deleted during sample collection；In Clinical Pathology：在 sample receipt、review、supervisor review 中录入/编辑/删除；在 sample tracking 功能中录入/编辑/删除。
- Event_Detail：`OBSERVED`（限定字段 Y/N）、`PretestAnimalNumber`、`SampleTubeID`、`GENERATION`、`TYPES`、`SupervisoryReview`（限定字段 Y/N）、`SMTOBS_ID`（主键，Edit_Type `½/3`）、`AnaSmpTypeID`、`AnaSmpTypName`、`DateTaken`、`SessionName`、`SampleObsDescriptorID`、`SampleObsDescriptorText`。
- 请求参数（Tag — 说明，Required）：
  - `StartDateTime` / `EndDateTime` — 时间窗（含/不含）（N）
  - `StudyName` — 专题或 colony 名（Y）
  - `Generation` — 代数（**原文 Required 列被说明文字占用，表格错位**）
  - `Types` — 1=colony，2 或 null=study（N）
  - `SampleTubeID` — 样本管条码（N）
  - `SMTOBS_ID` — 样本观察数据索引（N）
  - `N` — 最大记录数（N）
- 响应（父标签 `<AnimalSampleInfo>`；观察项子标签 `<SampleObsInfo>`）：
  - 顶层：`#StudyName`、`#Generation`、`#Types`、Count（按测量名/专题计数）
  - `#SampleTubeID` / SampleTubeKey / `#DateTaken` — 样本管与取数时间
  - `#AnimalID` / `#StudyAnimalNumber` / `#PretestAnimalNumber` / `#ColonyID` — 动物标识
  - ProtocolID / `#Session` / `#SessionName` / StudyName — 协议、session、专题
  - `<SampleObsInfo>`（每个观察重复）：SampleObsDataID、`#SampleObsDescriptorID`、SampleObsDescriptorText、SampleObsDescriptorForeignText、TypeID、TypeText、TypeText Foreign（原文名称含空格）、`#AnaSmpTypeID`、AnaSmpTypName、AnaSmpTypNameForeign、SignUserID、SignUserName、SignDateTime、SignMeaning、EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、DeleteFlag、EditFlag
  - 脚注 `#`：DeleteFlag=Y 时除主键（SampleObsDataID）外，交替键中非空列也要返回。

### CellMorphology（Cell Morphology）

- 说明：取细胞形态（含观察项/修饰符明细）数据；血细胞计数仪写入或动物房编辑/删除时触发，只读。
- 触发事件：In Clinical Pathology：Cell morphology is entered for a tube through a cell counting instrument；In Animal room Edit mode：Edit/delete of cell morphology data。
- Qualified fields：`OBS_TAKEN`（Y=Observation is taken / N=Not taken）、`NORMAL`（Y=The animal was marked as Normal）。
- Event_Detail：`OBS_TAKEN`、`NORMAL`（限定字段）、`MeasurementName`、`PretestAnimalNumber`、`SampleTubeID`、`GENERATION`、`TYPES`、`INOB_ID`（主键，Edit_Type `½/3`）。
- 请求参数（Tag — 说明，Required）：
  - `StartDateTime` / `EndDateTime` — 时间窗（含/不含）（N）
  - `MeasurementName` — 一个或多个关注测量名（N）
  - `StudyName` — 专题或 colony 名（Y）
  - `Generation` — 多代研究代数，单代 0；缺省 0（N）
  - `Types` — 1=colony，2 或 null=study（N）
  - `StudyAnimalNumber` / `PretestAnimalNumber` / `ColonyID` — 动物标识（N）
  - `SampleTubeID` — 样本管条码（N）
  - `INOB_ID` — 细胞形态数据索引（N）
  - `Normal` — Y 只看标记 normal 的数据（N）
  - `ObsTaken` — Y 只看已观察数据（N）
  - `CountOnly` — Y 只关心条数（N）
  - `StudyDataFlag` — 空/无此 tag＝只返回 study 数据；1＝只返回 colony 关联数据；2＝两者都返回（N）
  - `N` — 最大记录数（N）
  - Event_Detail 的 name/value 对（N）
- 响应（父标签 `<CellMorphologyInfo>`；观察项子标签 `<ObsDataInfo>`）：
  - 顶层：`#StudyName`、`#Generation`、`#Types`、Count（按测量名计数）
  - MeasurementNameForeign / `#MeaDat_ID` / MeasurementName / InObID — 测量与细胞形态记录
  - `#SampleTubeID` / SampleTubeKey — 样本管
  - Normal / ObsTaken / NotTakenReason / Comments — 观察标记与注释
  - `#DateTaken` / CageNumber / GroupNumber / SubGroupNumber / ColonySubgroupName / ColonySubgroupForeignName
  - 其余含 SignUserID、SignUserName、SignDateTime、SignMeaning、ProPhsID、PmeaProID、DayOfPhase、`#Session`、`#SessionName`、SessionNameForeign、ScheduledFlag、RealTime、EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、EntryMethodID、EntryMethodName、EntryMethodNameForeign、`#AnimalID`、`#StudyAnimalNumber`、`#PretestAnimalNumber`、`#ColonyID`、ColonyFlag、DeleteFlag、EditFlag 等
  - `<ObsDataInfo>`（每个观察重复）：ObsDataID、StudyCategoryID、CategoryID、CategoryName、CategoryNameForeign、SubCategoryID、StudySubCategoryID、SubCategoryName、SubCategoryNameForeign、SeverityID/StudySeverityID/SeverityName/SeverityForeignName、LocationID/StudyLocationID/LocationName/LocationForeignName、SizeID/StudySizeID/SizeName/SizeForeignName、Modifier_1ID/Name/ForeignName、Modifier_2ID/Name/ForeignName、Modifier_3ID/Name/ForeignName、NumericalID/NumericalName/NumericalForeignName/Value/Units、Modifiers、SignComment
  - 脚注 `#`：DeleteFlag=Y 时除主键外，交替键中非空列也要返回。

### ClinicalObs（Animal Standard Clinical Observations）

- 说明：取标准临床观察（含观察项与修饰符明细，必要时含体温等参数数据）；临床观察新增/编辑/删除时触发，只读。
- 触发事件：New clinical observation data for an animal in the Colony/Study；Edit/Delete clinical observation data for an animal in the Colony/Study。
- Qualified fields：`OBS_TAKEN`（Y/N）、`NORMAL`（Y）。
- Event_Detail：`OBS_TAKEN`、`NORMAL`、`StudyName`（限定字段）、`MeasurementName`、`PretestAnimalNumber`、`GENERATION`、`TYPES`、`INOB_ID`（主键，Edit_Type `½/3`）。
- 请求参数（Tag — 说明，Required）：
  - `StartDateTime` / `EndDateTime` — 时间窗（含/不含）（N）
  - `MeasurementName` — 一个或多个关注测量名（N）
  - `MeasurementType` — 测量类型索引（用于区分标准临床观察与 time critical observation）（N）
  - `StudyName` — 专题或 colony 名（Y）
  - `Generation` — 多代研究代数，单代 0；缺省 0（N）
  - `Types` — 1=colony，2 或 null=study（N）
  - `GroupNumber` — 一个或多个关注组号（N）
  - `StudyAnimalNumber` / `PretestAnimalNumber` / `ColonyID` — 动物标识（N）
  - `INOB_ID` — 标准临床观察数据索引（N）
  - `Normal` — Y 只看标记 normal 数据（N）
  - `ObsTaken` — Y 只看已观察数据（N）
  - `IncludeSchedule` — Y 包含计划日，N/null 不包含，默认 N（N）
  - `StudyAnimalOnly` / `LatestDataOnly` — 只看专题动物 / 只取最新数据（不返回 EditFlag/DeleteFlag）（N）
  - `CountOnly` — Y 只关心条数（N）
  - `StudyDataFlag` — 参见 CellMorphology API 说明（N）
  - `N` — 最大记录数（N）
  - Event_Detail 的 name/value 对（N）
- 响应（父标签 `<InlifeObsInfo>`；观察项子标签 `<ObsDataInfo>`；体温参数附加 `<ParamDataInfo>`）：
  - 顶层：StudyName、Generation、Types、Count（按测量名计数）
  - MeasurementNameForeign / MeaDat_ID / MeasurementName / InObID / ScheduledDays — 测量与观察记录
  - Normal / NormalPhrase / ObsTaken / NotTakenReason / Comments / DateTaken — 观察结果与注释
  - CageNumber / GroupNumber / SubGroupNumber / ColonySubgroupName / ColonySubgroupForeignName
  - SignUserID / SignUserName / SignDateTime / SignMeaning — 签名
  - ProPhsID / PhaseName / PhaseNameForeign / PmeaProID / DayOfPhase / Session / SessionName / SessionNameForeign / ScheduledFlag — 阶段与 session
  - 其余含 RealTime、EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、EntryMethodID、EntryMethodName、EntryMethodNameForeign、AnimalID、StudyAnimalNumber、PretestAnimalNumber、ColonyID、TimePointRefText、ElapseTime、TimePostDose、DateTimeOfDose、ColonyFlag、DeleteFlag、EditFlag 等
  - `<ObsDataInfo>`（每个观察重复）：ObsDataID、StudyCategoryID、CategoryID、CategoryName、CategoryNameForeign、SubCategoryID、StudySubCategoryID、SubCategoryName、SubCategoryNameForeign、SeverityID/StudySeverityID/SeverityName/SeverityForeignName/SeverityLevel、LocationID/StudyLocationID/LocationName/LocationForeignName/StudyFocus、SizeID/StudySizeID/SizeName/SizeForeignName、Modifier_1ID/Name/ForeignName、Modifier_2ID/Name/ForeignName、Modifier_3ID/Name/ForeignName、NumericalID/NumericalName/NumericalForeignName/Value/Units、Modifiers、SignComment
  - 注意：若标准临床观察测量中包含 "Body Temperature" 型参数，响应会额外返回 `<ParamDataInfo>`（字段见 GenMeas API）。

### ProductAdmin（Animal Product Administration）

- 说明：取（产品/化合物）给药施用记录（colony 场景）；产品施用数据新增/编辑/删除时触发，只读。
- 触发事件：New product administration data for an animal；Edit/Delete product administration data for an animal。
- Qualified field：`DOSE_STATUS`（1=Administered，2=Not Administered）。
- Event_Detail：`DOSE_STATUS`（限定字段）、`MeasurementName`（Informational）、`PRADMIN_ID`（主键，Edit_Type `½/3`）。
- 请求参数（Tag — 说明，Required）：
  - `StartDateTime` / `EndDateTime` — 时间窗（含/不含）（N）
  - `MeasurementName` — 一个或多个关注测量名（N）
  - `StudyName` — colony 名（Y）
  - `ColonyID` — Colony 动物号（N）
  - `PRADMIN_ID` — 产品施用记录索引（**原文 Required 列为空**）
  - `CountOnly` — Y 只关心条数（N）
  - `Types` — 1=colony，2 或 null=study（N）
  - `N` — 最大记录数（N）
  - Event_Detail 的 name/value 对（N）
- 响应（父标签 `<ProductAdminInfo>`）：
  - 顶层：MeasurementName、Count（按测量名计数）
  - MeasurementNameForeign / ProductAdminID — 测量外文名 / 产品施用记录索引
  - SupplierID / SupplierName / CompoundID / CompoundName / BatchLotNumber / ExpirationDate — 供应商与化合物批次
  - UsedBW / BWParamID / BWDateDataTaken / CalculatedDose — 计算所用体重、体重参数、体重取值时间、计算剂量
  - DoseStatus / NotTakenReason / DoseGivenText / DoseGivenNumeric / StorageUnit — 给药状态、未给原因、实给量
  - SignUserID / SignUserName / SignDateTime / SignMeaning — 签名
  - Session / SessionName / SessionNameForeign / ScheduledFlag / DayOfPhase — session 与阶段日
  - 其余含 RealTime、EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、EntryMethodID、EntryMethodName、AnimalID、ColonyID、ColonySubgroupName、ColonySubgroupForeignName、Comments、DeleteFlag、EditFlag 等

### FoodConsumption（Food and Water Consumption）

- 说明：取饲料/饮水消耗数据（含空料盒、满料盒、加料明细）；消耗相关事件或满料盒标记未称重时触发，只读。
- 触发事件（Food consumption）：New Empty Feeder/Bottle data for a cage；Edit/Delete Empty Feeder/Bottle data for a cage；Edit/Delete Full/Refill Feeder/Bottle data for a cage。
- 触发事件（Full Feeder）：Insert Full Feeder/Bottle data for a cage which is marked not taken；Edit Full Feeder/Bottle data for a cage；Delete Full Feeder/Bottle data for a cage which is marked not taken。
- Qualified field：无（文档列 "Qualified field for food consumption" 但未给具体字段）。
- Event_Detail：`MeasurementName`、`CageNumber`、`GENERATION`、`FF_EF_ID`（主键，Edit_Type `½/3`）。
- 请求参数（Tag — 说明，Required）：
  - `StartDateTime` / `EndDateTime` — 时间窗（含/不含）（N）
  - `MeasurementName` — 一个或多个空料盒/水瓶测量名（N）
  - `MeasurementType` — 关注测量类型，2=empty feeder，5=empty water（N）
  - `StudyName` — 专题名（Y）
  - `Generation` — 多代研究代数，单代 0；缺省 0（N）
  - `CageNumber` — 关注笼号，多个以逗号分隔（N）
  - `IncludeDetail` — Y 时含明细（空料盒/满料盒/加料），N 时只含消耗与每日消耗信息（N）
  - `LatestDataOnly` — Y 只取最新数据，不返回 EditFlag/DeleteFlag（N）
  - `FF_EF_ID` — food/water 记录索引（可为 full feeder、empty feeder 或 refill feeder 的索引）（N）
  - `CountOnly` — Y 只关心条数（N）
  - `N` — 最大记录数（N）
  - Event_Detail 的 name/value 对（N）
- 响应（父标签 `<FoodConsumptionInfo>`；明细子标签 `<FeederInfo>`）：
  - 顶层：`#StudyName`、`#Generation`、Count（按测量名计数）
  - MeasurementNameForeign / `#MeasurementName` / MeasurementType / TypeName / TypeNameForeign — 空料盒测量与类型
  - `#DateTakenEF` / DateTakenFF / DayofPhaseEF / DayofPhaseFF / Spilled — 空/满料盒取数时间、阶段日、是否泼洒
  - WeightTaken / NotTakenReason / FoodConsumed / StorageUnitFC / Exclude / FoodConsumedPerDay / StorageUnitFCDay / ExcludeReason — 消耗值、排除标记与原因
  - AnimalIDs / StudyAnimalNumbers — 参与该笼 food/water 活动的全部动物 ID/专题动物号（逗号分隔）
  - `#CageNumber` / PhaseName / PhaseNameForeign / FootNote / ProPhaseID — 笼号与阶段
  - 其余含 DisplayUnitFC、DisplayDecimalFC、ReportUnitFC、ReportDecimalFC、DisplayUnitFCDay、DisplayDecimalFCDay、ReportUnitFCDay、ReportDecimalFCDay、Comments 等
  - `<FeederInfo>`（仅 `IncludeDetail=Y` 时，纳入计算的全部测量数据）：MeasurementName、MeasurementNameForeign、ParamName、ParamNameForeign、Abbreviation、DisplayUnit、DisplayDecimal、ReportUnit、ReportDecimal、FF_EF_ID、WeightTaken、NotTakenReason、RawWeight、StorageUnit、Exclude、ExcludeReason、DateTaken、CageNumber、Spilled、Types、TypesName、TypesNameForeign、SignUserID、SignUserName、SignDateTime、SignMeaning、ProPhsID、PmeaProID、DayOfPhase、Session、SessionName、SessionNameForeign、ScheduledFlag、RealTime、EntryMethodID、EntryMethodName、EntryMethodNameForeign、EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、DeleteFlag、EditFlag
  - 脚注 `#`：DeleteFlag=Y 时除主键外，交替键中非空列也要返回。

### FullFeeder（Food and Water Full Feeder not weighted）

- 说明：专用 API，仅返回未称重（Not Weighted）的饲料/饮水满料盒信息；任意时刻可调，只读。
- 触发事件：无/未实现（文档未列事件触发器；由 FoodConsumption 的 Full Feeder 事件覆盖）。
- 请求参数（Tag — 说明，Required）：与 FoodConsumption 相同的一张表（StartDateTime、EndDateTime、MeasurementName、MeasurementType(2/5)、StudyName(Y)、Generation、CageNumber、IncludeDetail、LatestDataOnly、FF_EF_ID、CountOnly、N、Event_Detail pairs）。
- 响应：与 FoodConsumption 完全相同的响应结构，父标签 `<FoodConsumptionInfo>`，明细 `<FeederInfo>`（字段清单同上）。

### MassTracking（Animal Mass Tracking bservation）

- 说明：取肿物（mass）跟踪观察数据（含每个肿物的长宽深、位置、描述符、融合/分离等）；肿物观察新增/编辑/删除时触发，只读。
- 触发事件：New Mass tracking/observation data for an animal in the Study；Edit/Delete Mass tracking/observation data for an animal in the Study。
- Qualified fields（原文标题仍写 "Standard Clinical Observations"）：`OBS_TAKEN`（Y/N）、`NORMAL`（Y）。
- Event_Detail：`OBS_TAKEN`、`NORMAL`、`StudyName`（限定字段）、`MeasurementName`、`PretestAnimalNumber`、`GENERATION`、`MASSOB_ID`（主键，Edit_Type `½/3`）。
- 请求参数（Tag — 说明，Required）：
  - `StartDateTime` / `EndDateTime` — 时间窗（含/不含）（N）
  - `MeasurementName` — 一个或多个关注测量名（N）
  - `StudyName` — 专题名（Y）
  - `Generation` — 多代研究代数，单代 0；缺省 0（N）
  - `StudyAnimalNumber` / `PretestAnimalNumber` — 动物标识（N）
  - `MASSOB_ID` — 肿物跟踪记录索引（N）
  - `Normal` / `ObsTaken` — 只看 normal / 只看已观察（N）
  - `IncludeParameter` — Y 时同时返回参数明细（N）
  - `GroupNumber` — 一个或多个关注组号（N）
  - `StudyAnimalOnly` / `LatestDataOnly` — 只看专题动物 / 只取最新数据（N）
  - `CountOnly` — Y 只关心条数（N）
  - `N` — 最大记录数（N）
  - Event_Detail 的 name/value 对（N）
- 响应（父标签 `<MassObsInfo>`；每个肿物子标签 `<MassDataInfo>`）：
  - 顶层：`#StudyName`、`#Generation`、Count（按测量名计数）
  - MeasurementNameForeign / MeasurementName / MassObsID — 测量与肿物跟踪记录
  - `*StorageUnitsL` / `*DisplayUnitsL` / `*DisplayDecimalL` / `*ReportUnitsL` / `*ReportDecimalL` — 长度单位与小数位
  - `*StorageUnitsW` / `*DisplayUnitsW` / `*DisplayDecimalW` / `*ReportUnitsW` / `*ReportDecimalW` — 宽度单位与小数位
  - `*StorageUnitsD` / `*DisplayUnitsD` / `*DisplayDecimalD` / `*ReportUnitsD` / `*ReportDecimalD` — 深度单位与小数位
  - Normal / ObsTaken / NotTakenReason / Comment / `#DateTaken` — 观察结果与注释
  - CageNumber / GroupNumber / SubGroupNumber — 笼号与组号
  - 其余含 SignUserID、SignUserName、SignDateTime、SignMeaning、ProPhsID、PmeaProID、DayOfPhase、Session、SessionName、SessionNameForeign、ScheduledFlag、RealTime、EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、EntryMethodID、EntryMethodName、EntryMethodNameForeign、`#AnimalID`、`#StudyAnimalNumber`、`#PretestAnimalNumber`、DeleteFlag、EditFlag 等
  - `<MassDataInfo>`（每个肿物观察重复）：MassDaID、MassNumber、Length、MassLocID、MassLoc、MassLocForeign、Width、Depth、SizeTaken、Confirmed、Removed、Descriptor_1ID/RefID/Name/NameForeign、Descriptor_2ID/RefID/Name/NameForeign、Descriptor_3ID/RefID/Name/NameForeign、Descriptor_4ID/RefID/Name/NameForeign、Descriptor_5ID/RefID/Name/NameForeign、Descriptor_6ID/RefID/Name/NameForeign、DataComment、ConvergeRecID（肿物 2 与肿物 1 融合时该列为 1 且 Removed=Y）、DivergeRecID
  - 脚注 `#`：DeleteFlag=Y 时除主键（MassObsID）外，交替键中非空列也要返回。

### DirectDosing（Direct dosing）

- 说明：取直接给药数据（含剂量方案、化合物信息、体重要求、时间点等）；直接给药新增/编辑/删除时触发，只读。
- 触发事件：New direct dosing data for an animal；Edit/Delete direct dosing data for an animal。
- Qualified field：`DOSE_STATUS`（1=Dose given，2=Not dosed，3=Partially dosed）。
- Event_Detail：`DO½STATUS`（原文如此，实为 `DOSE_STATUS`；取值列 `½/3`＝1/3，限定字段）、`MeasurementName`、`PretestAnimalNumber`、`GENERATION`、`DIRDOS_ID`（主键，Edit_Type `½/3`）。
- 请求参数（Tag — 说明，Required）：
  - `StartDateTime` / `EndDateTime` — 时间窗（含/不含）（N）
  - `MeasurementName` — 一个或多个关注测量名（N）
  - `StudyName` — 专题名（Y）
  - `Generation` — 多代研究代数，单代 0；缺省 0（N）
  - `StudyAnimalNumber` / `PretestAnimalNumber` — 动物标识（N）
  - `GroupNumber` — 一个或多个关注组号（N）
  - `DoseStatus` — 给药状态（1/2/3）（N）
  - `DIRDOS_ID` — 直接给药记录索引（N）
  - `LatestDataOnly` — Y 只取最新数据，不返回 EditFlag/DeleteFlag（N）
  - `CountOnly` — Y 只关心条数（N）
  - `N` — 最大记录数（N）
  - Event_Detail 的 name/value 对（N）
- 响应（父标签 `<DirectDosingInfo>`；化合物子标签 `<ProCompoundInfo>`）：
  - 顶层：`#StudyName`、`#Generation`、Count（按测量名计数）
  - MeasurementNameForeign / MeasurementName / TotalNumDoseQty / LastDoseDateTime / FirstDoseDateTime / DirDosID — 测量、给药总量与首末给药时间
  - ProArticleID / ArticleID / ArticleName / ArticleNameForeign — 剂量方案（regimen）
  - Calculation / CalculationName / CalculationNameForeign / Rate / RateUnits / RateType / RateTypeName / RateTypeNameForeign / Tolerance — 计算方式、速率、速率类型、容差
  - LotBatch / SiteOfAdmin / TimePointRefText / ReferenceTime / Duration / ElapseTime / EndDateTaken / StudyFocus / RouteOfAdmin — 批号、给药部位、时间点、时长、途径
  - Accuracy / AccuracyUnits / Tolerance / CalculatedDose / DoseUnits / DoseGiven / DoseTime / DateTaken — 准确度、计算与实际给药量
  - 其余含 CageNumber、GroupNumber、SubGroupNumber、SignUserID、SignUserName、SignDateTime、SignMeaning、ProPhsID、PhaseName、PmeaProID、DayOfPhase、Session、SessionName、SessionNameForeign、ScheduledFlag、RealTime、EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、DoseStatus、DoseStatusName、DoseStatusNameForeign、BodyWeightUsed、BodyWeightUnits、DoseType（1- Measure dose；2- timed dosed）、DoseTypeName、DoseTypeNameForeign、NotTakenReason、CapsulePresented、CapsuleGiven、EntryMethodID、EntryMethodName、EntryMethodNameForeign、AnimalID、StudyAnimalNumber、PretestAnimalNumber、Sex、DeleteFlag、EditFlag 等
  - `<ProCompoundInfo>`：ProCompoundID、CompoundCode、Name、CompoundType、CompoundTypeName、CompoundTypeNameForeign、CompoundForm、CompoundFormName、CompoundFromNameForeign（原文拼写）、Biologic、LongName、Units、Decimal、DoseLevel
  - 注意：原文响应表中 `Tolerance` 出现两次（第 15、第 31 行位置）。

### IndirectDosing（Indirect dosing）

- 说明：取间接给药（经饲料/饮水摄入推算）数据；空料盒事件发生时触发，只读。
- 触发事件：When an empty feeder event occurs。
- Event_Detail：无（文档未给 Event_Detail 表）。
- 请求参数（Tag — 说明，Required）：
  - `StartDateTime` — 空料盒数据在此时间之后（含）录入（N）
  - `EndDateTime` — 空料盒数据在此时间之前（不含）录入（N）
  - `MeasurementName` — 一个或多个关注测量名（N）
  - `StudyName` — 专题名（Y）
  - `GroupNumber` — 一个或多个关注组号（N）
  - `Generation` — 多代研究代数，单代 0；缺省 0（N）
  - `FF_EF_ID` — 空料盒 food/water 记录索引（可为 full/empty/refill feeder 索引）（N）
- 响应（父标签 `<IndirectDosingInfo>`；化合物子标签 `<ProCompoundInfo>`）：
  - MeasurementName / MeasurementNameForeign — 测量名与外文名
  - ProArticleID / ArticleID / ArticleName / ArticleNameForeign — 剂量方案
  - Calculation / CalculationName / CalculationNameForeign / Rate / RateUnits / RateType / RateTypeName / RateTypeNameForeign / Tolerance — 计算方式与速率
  - LotBatch / RouteOfAdmin / Accuracy / AccuracyUnits / DoseType / DoseTypeName / DoseTypeNameForeign — 批号、途径、准确度、给药类型
  - Concentration / ConcentrationUnits / AvgFC / AvgFCUnits / AvgBW / AvgBWUnits — 浓度、日均摄食量、平均体重
  - DateTakenFF / DateTakenEF / CageNumber / GroupNumber / SubGroupNumber — 满/空料盒取数时间与笼组信息
  - 其余含 DayOfPhaseFF、DayOfPhase、ScheduledFlagFF、ScheduledFlag、AnimalID、StudyAnimalNumber、PretestAnimalNumber、ProPhsID 等
  - `<ProCompoundInfo>`：同 DirectDosing 的化合物字段（ProCompoundID、CompoundCode、Name、CompoundType(…)、CompoundForm(…)、Biologic、LongName、Units、Decimal、DoseLevel）

### DataDateRange（Date range for measurement data）

- 说明：取某一测量类型的最早/最新数据时间以及记录数；任意时刻可调，只读。
- 触发事件：无/未实现（文档未列事件触发器）。
- 请求参数（Tag — 说明，Required）：
  - `StudyName` — 专题名（Y）
  - `Types` — 1=colony，2 或 null=study（N）
  - `Generation` — 多代研究代数，单代 0；缺省为全部代（N）
  - `MeasurementType` — 一个测量类型，取值见下表（Y）
- 响应（父标签 `<MeasurementDataInfo>`）：
  - MeasurementType — 测量类型索引
  - StartDateTime — 该测量记录入库的最早时间（数据库时间，无需时区换算）
  - EndDateTime — 该测量记录入库的最晚时间（数据库时间，无需时区换算）
  - N — 该测量的记录数
- Data Date Range measurement type table（原文短表，原样保留）：
  | Index | Type Name | Table | Comment |
  |---|---|---|---|
  | 101 | Body Weights | BODY_WEIGHT | |
  | 104 | Standard Clinical Observation | INLIFE_OBSERVATION | |
  | 106 | Mass Tracking | MASS_OBSERVATION | |
  | 109 | Direct Dosing | DIRECT_DOSING | |
  | 110 | Indirect Dosing | FOOD_CONSUMPTION | For both types = 2 and 5 |
  | 123 | Empty Water Bottle Weights | FOOD_CONSUMPTION | types = 5 |
  | 153 | Empty Feeder Weights | FOOD_CONSUMPTION | types = 2 |

---

## 十、剖检类

### OrganWeight（Organ Weights）

- 说明：取脏器重量数据（含左/右成对组织与参数明细）；脏器重量新增/编辑/删除时触发，只读。
- 触发事件（新增/编辑）：New organ weight data for an animal；Edit organ weight data for an animal。删除事件独立：Delete organ weights data for an animal（Event_Detail 另加 `TissueName`）。
- Qualified field：`WEIGHT_TAKEN`（Y=Weight is taken / N=Not taken）。
- Event_Detail：`WEIGHT_TAKEN`（限定字段）、`MeasurementName`、`PretestAnimalNumber`、`GENERATION`、`ORGWGT_ID`（主键，Edit_Type `½/3`）；删除事件表另有 `TissueName`。
- 请求参数（Tag — 说明，Required）：
  - `StartDateTime` / `EndDateTime` — 时间窗（含/不含）（N）
  - `MeasurementName` — 一个或多个关注测量名（N）
  - `StudyName` — 专题名（Y）
  - `Types` — 1=colony，2 或 null=study（N）
  - `Generation` — 多代研究代数，单代 0；缺省 0（N）
  - `StudyAnimalNumber` / `PretestAnimalNumber` — 动物标识（N）
  - `WeightTaken` — Y 只看已称重数据（N）
  - `CountOnly` — Y 只关心条数（N）
  - `GroupNumber` — 一个或多个关注组号（N）
  - `IncludeParameter` — Y 同时返回脏器重量参数数据（N）
  - `ORGWGT_ID` — 脏器重量记录主键（N）
  - `N` — 最大记录数（N）
  - Event_Detail 的 name/value 对（N）
- 响应（父标签 `<OrganWeightInfo>`）：
  - StudyName / MeasurementName / Count（按测量名的记录数）
  - MeasurementNameForeign / OrganWeightID / TissueID / ProTissueID / TissueName / TissueNameForeign / TissueAbbr / TissueSex — 组织信息
  - `*ParamName` / `*ParamNameForeign` / `*Abbreviation` / `*DisplayDecimal` / `*DisplayUnit` / `*ReportDecimal` / `*ReportUnit` / `*TBWDisplayDecimal` / `*TBWReportDecimal` / `*BRNDisplayDecimal` / `*BRNReportDecimal` — 参数与 OW/TBW、OW/BRN 比值小数位
  - WeightTaken / NotTakenReason / RawWeight / StorageUnit / Exclude / ExcludeReason — 称重与排除
  - Status / StatusName / StatusNameForeign / Types（11- Non-Pair Tissue / 101- Left Pair Tissue / 102 – Right Pair Tissue）/ TypesName / TypesNameForeign / Comment
  - 其余含 SignUserName、SignDateTime、SignMeaning、ProPhsID、PmeaProID、DayOfPhase、ScheduledFlag、RealTime、EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、EntryMethodID、AnimalID、EntryMethodName、EntryMethodNameForeign、StudyAnimalNumber、PretestAnimalNumber、DeleteFlag、EditFlag
  - 脚注 `*`：仅当请求 `IncludeParameter=Y` 时可用。

### TermBodyWeight（Terminal Body Weights）

- 说明：取终末体重数据；终末体重新增/编辑/删除时触发，只读。
- 触发事件：New terminal body weight data for an animal；Edit/Delete terminal body weight data for an animal。
- 注意：文档原文 — `Please refer to 12.2.5.1 Body Weights section for Qualified field, event detail, Request and Respons for this API.`（限定字段、Event_Detail、请求与响应全部引用 BodyWeight API；无独立字段表）。

### GrossObs（Gross Observations）

- 说明：取大体观察（剖检大体与组织镜像大体观察）数据；新增/编辑/删除（阳性清除或虚线化）时触发，只读。
- 触发事件：
  - 大体观察（PM_FINDING_DATA）：New gross observations data for an animal；Edit gross observations data for an animal（排除从阳性改为虚线）；Edit Study Finding（参见 Micro Observations）。
  - Gross Tissue observations（PM_TISS_FIND_DATA）：New / Edit gross tissue observations data for an animal。
  - Delete Finding：当组织上的阳性发现被清除或虚线化时。
- Qualified field：`SIGN_OFF`（Y=If the animal passed completion check）。
- Event_Detail（三张表）：
  - 大体观察：`SIGN_OFF`（限定）、`PMFDAT_ID`（主键，Edit_Type `½/3`）、`PMTFDT_ID`、`MeasurementName`、`GENERATION`、`PretestAnimalNumber`、`FindingListType`（6 – Gross Observations）、`TissueListType`（3 – Adult Gross Observations）。
  - 组织镜像大体：`SIGN_OFF`、`PMTFDT_ID`（主键）、`GENERATION`、`MeasurementName`、`PretestAnimalNumber`、`FindingListType`（6 – Micro Observations）、`TissueListType`（3 – Adult Microscopic Observations）。
  - 删除发现（原文表）：`SIGN_OFF`、`PMFDAT_ID`（主键）、`PMTFDT_ID`、`GENERATION`、`MeasurementName`、`PretestAnimalNumber`、`FindingListType`（6 – Gross Observations）、`TissueListType`、`TissueName`、`FindingName`、`LongForm`、`RelToTreatName`、`PrimaryCauseofDth`、`InstanceNum`、`PMFDREF_ID`、`PMORGFDREF_ID`、`TissueDashed`。
- 请求参数与响应：文档原文 — `Please refer to 12.2.8.1 Micro Observation section for Request and Respons for this API.`（请求/响应结构与 MicroObs 相同）。
- 注意：MicroObs 与 GrossObs 共用同一请求/响应结构（`<GrossObsInfo>` / `<TissueInfo>` / `<FindingInfo>`）。

### TissueStatus（Tissue Status）

- 说明：取胎儿/幼仔/成体组织状态（采集/组织学/显微等状态）数据；组织状态新增/编辑/删除时触发，只读。
- 触发事件：New tissue status data for a fetus or a pup, or an animal；Edit tissue status data ...；Delete tissue status data ...。
- Qualified field：`SIGN_OFF`（Y=If the fetal passed completion check）。
- Event_Detail（新增/编辑与删除两张近同表）：`SIGN_OFF`（限定）、`PRGNREF_ID`、`FetalID/PupNumber`、`MeasurementName`、`PretestAnimalNumber`、`StatusTypes`（1=Adult Necropsy Status (Tissue Collection)；2=Adult Histology Status；3=Adult Micro Status；4=Fetal Status；5=Pup Status；7=Adult Necropsy Status (Gross Observation)）、`FindingListType`、`TissueListType`、`TissueName`、`GENERATION`、`PMTSTA_ID`（主键，Edit_Type `½/3`）。
- 请求参数（Tag — 说明，Required）：
  - `StartDateTime` / `EndDateTime` — 时间窗（含/不含）（N）
  - `MeasurementName` — 一个或多个关注测量名（N）
  - `ReqType` — 1=fetus，2=pup，3=animal（Y）
  - `StudyName` — 专题名（Y）
  - `Generation` — 多代研究代数（Y）
  - `StatusTypes` — 组织状态类型索引（取值同上）（N）
  - `StudyAnimalNumber` / `PretestAnimalNumber` / `TissueName` / `FetalID/PupNumber` — 标识（N）
  - `SignOff` — Y 只看标记完成的胎儿（N）
  - `CountOnly` — Y 只关心条数（N）
  - `PMTSTA_ID` — 记录主键（N）
  - `N` — 最大记录数（N）
  - Event_Detail 的 name/value 对（N）
- 响应（父标签 `<TissueStatusInfo>`）：
  - StudyName / MeasurementName / MeasurementTypeName / Count
  - MeasurementNameForeign / PMTisStausID / ProgenyRefID / Comment / FetalID/PupNumber / FetalSex/PupSex（M, F, U, H）/ PupStudyAnmNum / PupRefNumber / GroupNumber / SubGroupNumber
  - SignUserID / SignUserName / SignDateTime / SignMeaning / AnimalID / StudyAnimalNumber / PretestAnimalNumber
  - ProTissueID / TissueID / TissueName / TissueNameForeign / Abbreviation / Types / NotTakenReason / Status / StatusName / StatusNameForeign / DateTaken / StudyFocus
  - 其余含 ProPhsID、PmeaProID、DayOfPhase、ScheduledFlag、RealTime、EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、EntryMethodID、EntryMethodName、EntryMethodNameForeign、DeleteFlag、EditFlag
  - 注意（原文脚注）：幼仔/胎儿组织采集时以下 tag 不适用（因其非数据主来源）：`<Comment>`、`<DateTaken>`、`<DayOfPhase>`、`<ScheduledFlag>`、`<RealTime>`、`<EntryMethodID>`、`<EntryMethodName>`、`<EntryMethodNameForeign>`。

### AnimalComment（Animal Comment）

- 说明：取尸检测量数据采集中录入的动物（/胎儿/幼仔）注释；新增/编辑/删除时触发，只读。
- 触发事件：New animal comment data for an animal, a fetus or a pup；Edit/Delete animal comment data for an animal, a fetus or a pup。
- Qualified field：`SIGN_OFF`（Y=If the fetal passed completion check）。
- Event_Detail：`SIGN_OFF`（限定）、`PRGNREF_ID`、`FetalID/PupNumber`、`MeasurementName`、`PretestAnimalNumber`、`GENERATION`、`PMACMT_ID`（主键，Edit_Type `½/3`）、`ReqType`（1- fetus，2 – pup，3 – Animal）。
- 请求参数（Tag — 说明，Required）：
  - `StartDateTime` / `EndDateTime` — 时间窗（含/不含）（N）
  - `MeasurementName` — 一个或多个关注测量名（N）
  - `ReqType` — 1- fetus，2 – pup，3 – Animal（Y）
  - `StudyName` — 专题名（Y）
  - `Generation` — 多代研究代数（Y）
  - `StudyAnimalNumber` / `PretestAnimalNumber` / `FetalID/PupNumber` — 标识（N）
  - `SignOff` — Y 只看标记完成的胎儿/幼仔（N）
  - `PMACMT_ID` — 记录主键（N）
  - `CountOnly` — Y 只关心条数（N）
  - `N` — 最大记录数（N）
  - Event_Detail 的 name/value 对（N）
- 响应（父标签 `<AnimalCommentInfo>`）：
  - MeasurementType / MeasurementName / Count / MeasurementNameForeign
  - PMAnmCmtID / ProgenyRefID / Comment / FetalID/PupNumber / FetalSex/PupSex（M, F, U, H）/ PupStudyAnmNum / PupRefNumber / GroupNumber
  - AnimalID / StudyAnimalNumber / PretestAnimalNumber / DateTaken / PmeaProID / ProPhsID / PhaseName / ScheduledFlag / RealTime
  - 其余含 EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、EntryMethodID、EntryMethodName、EntryMethodNameForeign、SignUserID、SignUserName、SignDateTime、SignMeaning、DeleteFlag、EditFlag

---

## 十一、病理类

### MicroObs（Micropathology Observations）

- 说明：取显微病理观察（按动物→组织→发现三层：死亡信息/组织/发现与全部修饰符）数据；显微观察新增/编辑、Study Finding/Study Lexicon 编辑、组织清除、发现删除时触发，只读。
- 触发事件：
  - 显微观察（PM_FINDING_DATA）：New mciropathology observations data for an animal；Edit mciropathology observations data for an animal；Edit Study Finding（PM_STUDY_FINDING/PM_FINDING，取涉及的全部 Gross/Micro 记录）；Edit Study Lexicon（仅当 Modifier 被编辑时，不含 Modifier usage；取 PM_STUDY_MODIFIER/PM_STUDY_LOCATOR/PM_STUDY_NUM_MODIFIER 涉及的全部记录）。
  - 显微组织观察（PM_TISS_FIND_DATA）：New / Edit mciropathology tissue observations data for an animal；Delete Tissue（Clear a tissue for an animal）。
  - Delete Finding：阳性发现被清除或虚线化。
- Qualified field：`SIGN_OFF`（Y=If the animal passed completion check）。
- Event_Detail（三张表）：`SIGN_OFF`（限定）、`PMFDAT_ID`（主键，Edit_Type `½/3`）、`PMTFDT_ID`、`GENERATION`、`MeasurementName`、`PretestAnimalNumber`、`FindingListType`（7 – Micro Observations）、`TissueListType`（4 – Adult Microscopic Observations）、`TissueName`；删除发现表另加 `FindingName`、`LongForm`、`RelToTreatName`、`PrimaryCauseofDth`、`InstanceNum`、`PMFDREF_ID`、`PMORGFDREF_ID`、`TissueDashed`。
- 请求参数（Tag — 说明，Required）：
  - `StartDateTime` / `EndDateTime` — 时间窗（含/不含）（N）
  - `PMFDAT_ID` / `PMTFDT_ID` — 发现数据/组织发现记录索引（N）
  - `GrossFindingDataID` — 大体发现数据 ID（PMFDAT_ID），GrossObs API 用（N）
  - `MicroFindingDataID` — 显微发现数据 ID（PMFDAT_ID），MicroObs API 用（N）
  - `MeasurementName` — 一个或多个关注测量名（N）
  - `StudyName` — 专题名（Y）
  - `Generation` — 代数；缺省 0（N）
  - `StudyAnimalNumber` / `PretestAnimalNumber` — 动物标识（N）
  - `SignOff` — Y 只看标记完成的动物（N）
  - `ExcludeModifier` — Y 时不返回每个发现的修饰符数据（N）
  - `GroupNumber` — 一个或多个关注组号（N）
  - `MiChronMod` — 用作 Chronicity 的通用类型修饰符名，多个以逗号分隔（N）
  - `CountOnly` — Y 只关心条数（N）
  - `N` — 最大记录数（N）
  - Event_Detail 的 name/value 对（N）
- 响应（父标签 **`<GrossObsInfo>`（原文如此；动物层）**，其后 `<TissueInfo>` 每个组织重复、`<FindingInfo>` 每个发现重复）：
  - 顶层：`#StudyName`、`#Generation`、`#Types`（1 colony / 2 或 null study）、MeasurementName、Count
  - 动物层：Comment（mark dead）、DeathStatusID/StudyDeathStatusID/DeathStatus/DeathStatusForeign、DeathProPhaseID/DeathPhase/DeathPhaseForeign、DayOfPhase、DeathTime、Approximate、CageNumber/GroupNumber/SubGroupNumber、AnimalID/StudyAnimalNumber/PretestAnimalNumber
  - `<TissueInfo>`：MeasurementNameForeign、PMTissueFindID、ProTissueID、TissueID、Abbreviation、TissueName、TissueNameForeign、TissueDashed、TissueComment、SummaryTissueTypeName、SummaryTissueType（1=Reproductive tissue, maturity；2=Reproductive tissue, Cycle）、DateTaken`*`、ProPhsID、PmeaProID、DayOfPhase`**`、ScheduledFlag、RealTime、EntryDateTime、EntryOperator(ID/RefID)、SignUser(ID/Name/DateTime/Meaning)、EntryMethodID/Name/NameForeign、StudyFocus、DeleteFlag、EditFlag
  - `<FindingInfo>`：FindingDataID、FindingDashed、StudyFindingID、PMFDREF_ID、FindingName(Foreign)、PMORGFDREF_ID、OrgFindingName(Foreign)、OrgFindingDataID、OrgNeoplasmType、OrgLongForm(Foreign)、OrgTissueName(Foreign)、OrgRelToTreatName、EarliestMassDT、FindingComment、StudyFocus、InstanceNum、FindingNum、FindingType/TypeName/NameForeign、NeoplasmType/Name/NameForeign、LongForm(Foreign)、Modifiers、Modifiers2、SeverityRefID/SeverityID/StudySeverityID/Name/ForeignName/DisplaySymbol、Location*、Size*、Modifier_1..6ID/Study/Name/ForeignName/DisplaySymbol、NumericalID/Study/N ame/ForeignName/Value/Units、ShortText*、RelToTreat*、Distribution*、RelToDeath*、PrimaryCauseofDth、Entry*/Sign*、ChronicityName
  - 注意：MicroObs 与 GrossObs 共用本结构；`EarliestMassDT` 与 `Multiple Instance Number` 的算法在原文中有专门小节（依据 pm_finding_correlation、MASS_DATA、pm_std_fnd_locator 推导）;`*` 骨骼/固定报告日期为尸检后入库日；`**` 组织层 DayOfPhase 为空。

### Correlation（Correlation）

- 说明：取发现关联（大体-显微、肿物-发现等）数据；关联新增/编辑/删除时触发，只读。
- 触发事件：New Correlation data for an animal；Edit/Delete Correlation data for an animal。
- Event_Detail：`PMFCOR_ID`（主键，Edit_Type `½/3`）、`GENERATION`、`MeasurementName`、`PretestAnimalNumber`、`GrossFindingDataID`、`MicroFindingDataID`、`CorrType`、`GrossInstanceNum`、`GrossTissueName`、`MicroInstanceNum`、`MicroTissueName`、`CorrStatus`。
- 请求参数（Tag — 说明，Required）：
  - `StartDateTime` / `EndDateTime` — 时间窗（含/不含）（N）
  - `PMFCOR_ID` — 关联记录主键（N）
  - `GrossFindingDataID` — 大体发现数据 ID（PMFDAT_ID_GROSS），若请求含 PMFCOR_ID 则忽略（N）
  - `MicroFindingDataID` — 显微发现数据 ID（PMFDAT_ID_MICRO），若请求含 PMFCOR_ID 则忽略（N）
  - `MeasurementName` — 一个或多个关注测量名（N）
  - `StudyName` — 专题名（Y）
  - `Generation` — 代数；缺省 0（N）
  - `StudyAnimalNumber` / `PretestAnimalNumber` — 动物标识（N）
  - `CorrType` / `CorrStatus` — 关联类型/状态（N）
  - `CountOnly` — Y 只关心条数（N）
  - `N` — 最大记录数（N）
  - Event_Detail 的 name/value 对（N）
- 响应（父标签 `<CorrelationInfo>`）：
  - StudyName / Generation / Types / MeasurementName / Count / MeasurementNameForeign
  - PMCorrID、AnimalID、StudyAnimalNumber、PretestAnimalNumber
  - ProTissueID/TissueID/Abbreviation/TissueName/TissueNameForeign、ProGrossTissueID/GrossTissueID/GrossAbbreviation/GrossTissueName/GrossTissueNameForeign（显微-大体关联时）
  - InObID / ObsDataID / MassDaID / GrossFindingDataID / MicroFindingDataID
  - CorrType / CorrTypeName / CorrTypeNameForeign / CorrStatus / CorrStatusName / CorrStatusNameForeign / Comment / DateTaken / PmeaProID / ScheduledFlag / RealTime
  - 其余含 EntryOperator、EntryOperatorID、EntryOperatorRefID、EntryDateTime、SignUserID、SignUserName、SignDateTime、SignMeaning

---

## 十二、DART（发育与生殖毒性）类

### MatingMon（Mating Monitoring）

- 说明：取交配监测数据；交配监测新增/编辑/删除时触发，只读。
- 触发事件：New Mating Monitor data for a dam；Edit/Delete Mating Monitor data for a dam。
- Qualified field：`OBSERVED`（Y=Observed / N=Not observed）。
- Event_Detail：`OBSERVED`（限定）、`MeasurementName`、`PretestAnimalNumber`、`GENERATION`、`MATDAT_ID`（主键，Edit_Type `½/3`）。
- 请求参数（Tag — 说明，Required）：`StartDateTime`、`EndDateTime`、`MeasurementName`、`StudyName`(Y)、`Generation`、`StudyAnimalNumber`（Dam）、`PretestAnimalNumber`（Dam）、`MATDAT_ID`、`Observed`、`CountOnly`、`N`、Event_Detail pairs（除 StudyName 外均 N）。
- 响应（父标签 `<MatingDataInfo>`）：
  - StudyName / Generation / MeasurementName / Count / MeasurementNameForeign
  - MatingDataID / Observed / NotTakenReason / SpermDate / InseminationDate / PlugCount / Copulation / Comment / DateTaken
  - CageNumber / GroupNumber / SubGroupNumber / SignUser(ID/Name/DateTime/Meaning) / ProPhsID / PmeaProID / DayOfPhase / Session / SessionName / SessionNameForeign / ScheduledFlag / RealTime
  - 其余含 EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、EntryMethodID、EntryMethodName、EntryMethodNameForeign、AnimalID、StudyAnimalNumber、PretestAnimalNumber、DeleteFlag、EditFlag

### EstrusCycleMon（Estrus Cycle Monitoring）

- 说明：取动情周期监测数据；新增/编辑/删除时触发，只读。
- 触发事件：New Estrus cycle monitoring data for a Dam；Edit/Delete Estrus cycle monitoring data for a Dam。
- Qualified field：`SLIDE_AVAILABLE`（Y=Slide available / N=No slide）。
- Event_Detail：`SLIDE_AVAILABLE`（限定）、`MeasurementName`、`PretestAnimalNumber`、`GENERATION`、`ESTDAT_ID`（主键，Edit_Type `½/3`）。
- 请求参数（Tag — 说明，Required）：`StartDateTime`、`EndDateTime`、`MeasurementName`、`StudyName`(Y)、`Generation`、`StudyAnimalNumber`（Dam）、`PretestAnimalNumber`（Dam）、`ESTDAT_ID`、`SlideAvailable`、`CountOnly`、`N`、Event_Detail pairs（除 StudyName 外均 N）。
- 响应（父标签 `<EstrusDataInfo>`）：
  - StudyName / Generation / MeasurementName / Count / MeasurementNameForeign
  - EstrusDataID / SlideAvailable / NotTakenReason / StudyEstrusID / EstrusName / EstrusForeign / Comment / DateTaken
  - CageNumber / GroupNumber / ProPhsID / SubGroupNumber / SignUser(ID/Name/DateTime/Meaning) / PmeaProID / DayOfPhase / Session / SessionName / SessionNameForeign / ScheduledFlag / RealTime
  - 其余含 EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、EntryMethodID、EntryMethodName、EntryMethodNameForeign、AnimalID、StudyAnimalNumber、PretestAnimalNumber、DeleteFlag、EditFlag

### EstrusObs（Estrus Observation）

- 说明：取动情观察数据；新增/编辑/删除时触发，只读。
- 触发事件：New Estrus observation data for a dam；Edit/Delete Estrus observation data for a dam。
- Qualified fields：`OBS_TAKEN`（Y=Observation is taken / N=Not taken）、`NORMAL`（Y=The dam was marked as Normal）。
- Event_Detail：`OBS_TAKEN`、`NORMAL`、`StudyName`（均限定字段）、`MeasurementName`、`PretestAnimalNumber`、`GENERATION`、`TYPES`、`INOB_ID`（主键，Edit_Type `½/3`）。
- 请求参数与响应：文档原文 — `Request parameters and Response- Estrus observations data in XML format, plese refer to Animal Standard Clinical Observations section.`（引用 ClinicalObs API 结构）。

### OvaryExam（Ovary Exam）

- 说明：取卵巢检查（黄体数）数据；新增/编辑/删除及子宫检查中编辑卵巢数据时触发，只读。
- 触发事件：New Ovary Exam data for a Dam；Edit/Delete Ovary Exam data for a Dam；Edit of Ovary Exam data during an Uterine exam。
- Qualified field：`OBS_TAKEN`（Y=Ovary exam taken / N=Not taken）。
- Event_Detail：`OBS_TAKEN`（限定）、`MeasurementName`、`PretestAnimalNumber`、`GENERATION`、`CSECDA_ID`（主键，Edit_Type `½/3`）。
- 请求参数（Tag — 说明，Required）：`StartDateTime`、`EndDateTime`、`MeasurementName`、`StudyName`(Y)、`Generation`、`StudyAnimalNumber`（Dam）、`PretestAnimalNumber`（Dam）、`ObsTaken`、`CSECDA_ID`、`CountOnly`、`N`、Event_Detail pairs（除 StudyName 外均 N）。
- 响应（父标签 `<OvaryExamInfo>`）：
  - StudyName / Generation / MeasurementName / Count / MeasurementNameForeign
  - CsectionDataID / ObsTaken / NotTakenReason / CorporaLuteaLeft / CorporaLuteaRight / CorporaLuteaTotal / Comment / DateTaken
  - CageNumber / GroupNumber / SubGroupNumber / SignUser(ID/Name/DateTime/Meaning) / ProPhsID / PmeaProID / DayOfPhase / ScheduledFlag / RealTime
  - 其余含 EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、EntryMethodID、EntryMethodName、EntryMethodNameForeign、AnimalID、StudyAnimalNumber、PretestAnimalNumber、DeleteFlag、EditFlag

### Csection（C Section）

- ⚠️ **Category 名大小写敏感（生产实测）**：现网要用 `CSection`（大写 S）；
  文档拼写 `Csection` 被服务端拒（`Key=214002 Not signed on`）。
- 说明：取剖宫产数据（黄体、妊娠状态、着床数、子宫重量、死胎/活胎计数等）；新增/编辑/删除及子宫检查中编辑时触发，只读。
- 触发事件：New C Section data for a Dam；Edit/Delete C Section data for a Dam；Edit of C Section data during an Uterine exam。
- Qualified field：`OBS_TAKEN`（Y=C Section taken / N=Not taken）。
- Event_Detail：`OBS_TAKEN`（限定）、`MeasurementName`、`PretestAnimalNumber`、`GENERATION`、`CSECDA_ID`（主键，Edit_Type `½/3`）。
- 请求参数（Tag — 说明，Required）：`StartDateTime`、`EndDateTime`、`MeasurementName`、`StudyName`(Y)、`Generation`、`StudyAnimalNumber`（Dam）、`PretestAnimalNumber`（Dam）、`ObsTaken`、`CountOnly`、`CSECDA_ID`、`N`、Event_Detail pairs（除 StudyName 外均 N）。
- 响应（父标签 `<CsectionInfo>`）：
  - StudyName / Generation / MeasurementName / Count / MeasurementNameForeign
  - CsectionDataID / ObsTaken / NotTakenReason / CorporaLuteaLeft / CorporaLuteaRight / CorporaLuteaTotal
  - StudyPregnancyStatusID / PregnancyStatusRefID / PregnancyType（1 Pregnant / 2 not Pregnant）/ PregnancyTypeName(Foreign) / PregnancyStatusID（**原文重复两行**）/ PregnancyStatusName / PregnancyStatusForeign
  - ImplantLeft / ImplantRight / ImplantTotal / UterineWt / UterineWtUnits / UterineWtExclude / UterineWtDisUnits / UterineWtRptUnits / UterineWtDisDec / UterineWtRptDec / UterineWtExcludeReason / UterineWtEntryMethodID
  - VoidUterineWt / VoidUterineWtUnits / VoidUterineWtExclude / VoidUterineWtExcludeReason / VoidUterineWtEntryMethodID / VoidUterineWtDisUnits / VoidUterineWtRptUnits / VoidUterineWtDisDec / VoidUterineWtRptDec
  - SaclMethodName / Comment / MetrialGlands / DateTaken / CageNumber / GroupNumber / SubGroupNumber
  - 其余含 SignUserID、SignUserName、SignDateTime、SignMeaning、ProPhsID、PmeaProID、DayOfPhase、ScheduledFlag、RealTime、EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、EntryMethodID、EntryMethodName、EntryMethodNameForeign、AnimalID、StudyAnimalNumber、PretestAnimalNumber、DeleteFlag、EditFlag

### UterineExam（Uterine Exam）

- 说明：取子宫检查/胎儿明细（着床、胎序、胎性别、胎状态及每个胎儿的用户参数：羊水量、胎重、胎盘重）数据；胎儿新增/编辑/删除、胎儿明细录入/编辑/删除时触发，只读。
- 触发事件：New fetus data for a Dam；Edit/Delete fetus data for a Dam；New fetus detail entered；Edit/Delete fetus detail data。
- Qualified field：None（无）。
- Event_Detail：`MeasurementName`、`PretestAnimalNumber`、`GENERATION`、`UTREF_ID`（主键，Edit_Type `½/3`）、`PRGNREF_ID`（标识 pup）。
- 请求参数（Tag — 说明，Required）：`StartDateTime`、`EndDateTime`、`MeasurementName`、`StudyName`(Y)、`Generation`、`StudyAnimalNumber`（Dam）、`PretestAnimalNumber`（Dam）、`UTREF_ID`、`CountOnly`、`N`、Event_Detail pairs（除 StudyName 外均 N）。
- 响应（父标签 `<UterineRefInfo>`；每个胎儿的明细父标签 `<ParamDataInfo>`）：
  - StudyName / Generation / MeasurementName / Count / MeasurementNameForeign
  - UterineRefID / CsectionDataID / ImplantationID / Side（L/R）/ ObsAllocation / ObsAllocationName(Foreign) / FetalSequence / FetalSex（M, F, U, H）/ StatusID / StatusName(Foreign) / DateTaken
  - CageNumber / GroupNumber / SubGroupNumber / SignUser(ID/Name/DateTime/Meaning) / PmeaProID / ProPhsID / DayOfPhase / ScheduledFlag / RealTime
  - 其余含 EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、EntryMethodID、EntryMethodName、EntryMethodNameForeign、AnimalID、StudyAnimalNumber、PretestAnimalNumber、`DeleteFlag**`、`EditFlag**`
  - `<ParamDataInfo>`（每个胎儿重复；用户自定义参数、羊水量、胎重、胎盘重）：PrgnDatID、ProParamID、ParamID、Abbreviation、ParamName、ParamForeignName、ParamType、ParamUnits、ParamDataType、DisplayDecimal、DisplayUnit、ReportDecimal、ReportUnit、Exclude、ExclusionReason、TextValue、TextName、TextNameForeign、NumericValue、DateTime、DateTaken、ProPhsID、PhaseName、DayOfPhase、ScheduledFlag、RealTime、EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、EntryMethodID（1- Key entry；2 – Online；3 – calculated）、EntryMethodName、EntryMethodNameForeign、ProgenyRefID
  - 脚注 `**`（EditFlag/DeleteFlag 逻辑）：对 uterine_reference 的插入/更新与对 progeny_data 的插入/更新/删除且**无审计**＝insert（两 tag 均 null）；对 uterine_reference 带审计更新，或对胎儿明细（progeny_data）带审计插入/更新/删除＝update（`<EditFlag>Y</EditFlag>`）；对 uterine_reference 带审计删除＝delete（`<DeleteFlag>Y</DeleteFlag>`）；不带审计删除**也是** delete（`<DeleteFlag>Y</DeleteFlag>`）；不会为每个 `<ParamDataInfo>` 单独发 EditFlag/DeleteFlag。

### ProgenySex（Assign Fetal/Pup Sex）

- 说明：取胎儿/幼仔性别分配数据；分配/编辑/删除性别时触发，只读。
- 触发事件：Assign sex for a fetus or a pup；Edit/Delete sex for a fetus or a pup。
- Qualified field：None（无）。
- Event_Detail：`MeasurementName`、`PretestAnimalNumber`、`GENERATION`、`RPGSX_ID`（主键，Edit_Type `½/3`）、`PRGNREF_ID`、`PupNumber`、`FetalID`。
- 请求参数（Tag — 说明，Required）：
  - `StartDateTime` / `EndDateTime` / `MeasurementName` —（N）
  - `StudyName` — 专题名（Y）
  - `Generation` — 代数（N）
  - `StudyAnimalNumber` / `PretestAnimalNumber` — Dam 标识（N）
  - `FetalID` — 胎号（N）
  - `PupNumber` — 已编号 pup 的号；未编号时 "Pup " + pup reference number（N）
  - `RPGSX_ID` — Progeny sex 索引（N）
  - `N` — 最大记录数（N）
  - Event_Detail 的 name/value 对（N）
- 响应（父标签 `<ProgenySexInfo>`）：
  - StudyName / Generation / MeasurementName / MeasurementNameForeign / MeasurementType / MeasurementTypeName / Sex（M, F, U, H）
  - SignUserID / SignUserName / SignDateTime / SignMeaning / PmeaProID / ProPhsID / DayOfPhase / RealTime / EntryDateTime / EntryOperator / EntryOperatorID / EntryOperatorRefID / EntryMethodID / EntryMethodName / AnimalID / StudyAnimalNumber / PretestAnimalNumber
  - ProgenyRefID / FetalID / PupStudyNum / PupRefNumber / PupNumber / Comment

### FetalObs（Fetal Necropsy Observations）

- 说明：取胎儿尸检观察（大体/新鲜内脏/骨骼/固定内脏，按胎儿→组织→发现三层）数据；Mark Fetus Complete、胎儿组织观察、胎儿发现事件触发，只读。
- 触发事件：Mark fetus complete；Fetal Observation Finding（PM_FINDING_DATA）：New/Edit necropsy observation data for a fetus；Fetal Tissue Observations（PM_TISS_FIND_DATA）：New/Edit Fetal Tissue observations data for an animal;Delete Fetal Tissue（Clear tissue for a fetus）；Delete Finding（阳性清除或虚线化）。
- Qualified field：`SIGN_OFF`（Y=If the fetal passed completion check）。
- Event_Detail：`SIGN_OFF`（限定）、`PMFDAT_ID`（主键）、`PMTFDT_ID`、`PRGNREF_ID`、`GENERATION`、`FetalID`、`MeasurementName`、`PretestAnimalNumber`、`FindingListType`（8 – Fetal Observations）、`TissueListType`（101 Fetal Gross / 102 Fetal Fresh Visceral / 103 Fetal Skeletal / 104 Fetal Fixed Visceral Observations）。
- 请求参数（Tag — 说明，Required）：`StartDateTime`、`EndDateTime`、`MeasurementName`、`StudyName`(Y)、`Generation`、`StudyAnimalNumber`、`PretestAnimalNumber`、`FetalID`、`SignOff`、`PRGNREF_ID`、`PMTFDT_ID`、`PMFDAT_ID`、`CountOnly`、`N`、Event_Detail pairs（**原文 PMTFDT_ID 行 Required 列空、PMFDAT_ID 行为 N，属表格错位**）。
- 响应（父标签 **`<GrossObsInfo>`（原文如此）**；`<TissueInfo>`、`<FindingInfo>`）：
  - 顶层：MeasurementName / StudyName / Generation / Count
  - 胎儿层：ProgenyRefID、Comment、DeathStatusID/StudyDeathStatusID/DeathStatus(Foreign)、DeathProPhaseID/DeathPhase(Foreign)、DayOfPhase、DeathTime、Approximate、FetalID、FetalSex、CageNumber、GroupNumber、SubGroupNumber、PupStudyAnmNum、PupRefNumber、AnimalID、StudyAnimalNumber、PretestAnimalNumber
  - `<TissueInfo>`：MeasurementNameForeign、MEADAT_ID、MeasurementType、MeasurementTypeName、PMTissueFindID、ProTissueID、TissueID、NormalPhrase、TissueName(Foreign)、TissueDashed、TissueComment、DateTaken`*`、ProPhsID、PmeaProID、DayOfPhase`**`、ScheduledFlag、RealTime、Entry*/Sign*/DeleteFlag/EditFlag/EntryMethod*
  - `<FindingInfo>`：DeleteFlag、FindingDataID、FindingDashed、StudyFindingID、MasterFindingID、MasterFindingRefID、PMFDREF_ID、ReviewModUsage、ReviewModUsageText、FindingName(Foreign)、FindingComment、Modifiers、Modifiers2、Severity*、Location*、Sublocation*、Size*、Modifier_1..6*、Numerical*、Review*(ID/Study/Name/ForeignName/DisplaySymbol)、Classification*、Entry*/Sign*
  - 注意（原文脚注）：`*` 骨骼与固定报告显示 Dam 死亡日期/死亡阶段日，但数据库存的是尸检之后取数日期，API 的 TissueInfo DateTaken 即该后置日期；`**` 原始报告显示死亡阶段日，API 另含该对象存储的阶段日，但 TissueInfo 的 DayOfPhase 为空。

### Parturition（Parturition）

- 说明：取分娩数据（活产/死产/不确定数、妊娠天数与人工覆盖等）；新增/编辑/删除时触发，只读。
- 触发事件：New Parturition data for a Dam；Edit/Delete Parturition data for a Dam。
- Qualified field：`PARTURITION_STATUS`（0=Not Started / 1=In Progress / 2=Complete）。
- Event_Detail：`PARTURITION_STATUS`（限定，0/1/2）、`MeasurementName`、`PretestAnimalNumber`、`GENERATION`、`PARSES_ID`（主键，Edit_Type `½/3`）。
- 请求参数（Tag — 说明，Required）：`StartDateTime`、`EndDateTime`、`MeasurementName`、`StudyName`(Y)、`Generation`、`StudyAnimalNumber`（Dam）、`PretestAnimalNumber`（Dam）、`PARSES_ID`、`ParturitionStatus`（0/1/2；缺省全部）、`CountOnly`、`N`、Event_Detail pairs（除 StudyName 外均 N）。
- 响应（父标签 `<ParturitionInfo>`）：
  - MeasurementName / Count / StudyName / Generation / MeasurementNameForeign
  - ParturitionID / ParturitionStatusID / ParturitionStatusName / ParturitionStatusForeign
  - StudyPregnancyStatusID / PregnancyStatusRefID / PregnancyType（1 Pregnant / 2 not Pregnant）/ PregnancyTypeName(Foreign) / PregnancyStatusID / PregnancyStatusName / PregnancyStatusForeign
  - NumLiveborn / NumStillborn / NumUncertain / GestationLength / GLManualEntry / GLManualEntryReason / Comment / DateTaken
  - CageNumber / GroupNumber / SubGroupNumber / SignUser(ID/Name/DateTime/Meaning) / ProPhsID / PmeaProID / DayOfPhase / Session / SessionName / SessionNameForeign / ScheduledFlag / RealTime
  - 其余含 EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、AnimalID、StudyAnimalNumber、PretestAnimalNumber、DeleteFlag、EditFlag

### PupBodyWeight（Pup Body Weights）

- 说明：取幼仔体重数据（含参数明细）；幼仔体重新增/编辑/删除时触发（pup body weight 测量或含 pup weight 参数的 pup 广义测量均触发），只读。
- 触发事件：New body weight data for a pup；Edit/Delete body weight data for a pup。
- Qualified field：`WEIGHT_TAKEN`（Y=Weight is taken / N=Not taken）。
- Event_Detail：`WEIGHT_TAKEN`（限定）、`PRGNREF_ID`、`MeasurementName`、`PretestAnimalNumber`、`PupNumber`、`GENERATION`、`BW_ID`（主键，Edit_Type `½/3`）。
- 请求参数（Tag — 说明，Required）：`StartDateTime`、`EndDateTime`、`MeasurementName`、`StudyName`(Y)、`Generation`、`StudyAnimalNumber`、`PretestAnimalNumber`、`PupNumber`、`WeightTaken`、`BW_ID`、`IncludeParameter`、`CountOnly`、`N`、Event_Detail pairs（除 StudyName 外均 N）。
- 响应（父标签 `<BodyWeightInfo>`）：
  - MeasurementName / StudyName / Count / MeasurementNameForeign
  - BodyWeightID / WeightTaken / NotTakenReason / RawWeight / StorageUnit
  - `*ParamName` / `*ParamNameForeign` / `*Abbreviation` / `*DisplayDecimal` / `*DisplayUnit` / `*ReportDecimal` / `*ReportUnit` / Exclude / ExcludeReason
  - DateTaken / CageNumber / GroupNumber / SubGroupNumber / SignUser(ID/Name/DateTime/Meaning) / ProPhsID / PmeaProID / DayOfPhase / Session / SessionName / SessionNameForeign / ScheduledFlag / RealTime
  - 其余含 EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、EntryMethodID、AnimalID、EntryMethodName、EntryMethodNameForeign、StudyAnimalNumber、PretestAnimalNumber、ProgenyRefID、PupNumber、PupSex（M, F, U, H）、PupStudyNum、PupRefNumber、DeleteFlag、EditFlag
  - 脚注 `*`：仅 `IncludeParameter=Y` 时可用。
  - **本 API 在原文中附有完整的请求 XML Schema、响应 XML Schema 及请求/响应示例（约第 5805~6129 行）。最简请求示例（原文）**：
    ```xml
    <?xml version="1.0" encoding="UTF-8" ?>
    <PTS>
    <Doctype> PTS_RQ_STUDY_DATA </Doctype>
    <Category>PupBodyWeight</Category>
    <StartDateTime>14-Jun-2008 17:20:12.00</StartDateTime>
    <EndDateTime>20-Jun-2008 17:20:12.000 </EndDateTime>
    <StudyName>08-0810</StudyName>
    <N>100</N>
    </PTS>
    ```
  - 注意：PDF 提取使该段 schema/示例中 `name=”=”X””` 形式与 `<PMeaProIDPmeaProID>32</PMeaProIDPmeaProID>`（原文 `<xsd:element name=”PmeaProID”=”PmeaProID” .../>` 的错行）等为提取损坏，正常应为 `name="X"` / `<PmeaProID>`。

### PupDirectDosing（Pup Direct dosing）

- 说明：取幼仔直接给药数据（含化合物信息）；新增/编辑/删除时触发，只读。
- 触发事件：New direct dosing data for a pup；Edit/Delete direct dosing data for a pup。
- Qualified field：`DOSE_STATUS`（1=Dose given / 2=Not dosed / 3=Partially dosed）。
- Event_Detail：`DO½STATUS`（原文如此，实为 `DOSE_STATUS`；取值 `½/3`＝1/3）、`PRGNREF_ID`、`MeasurementName`、`PretestAnimalNumber`、`PupNumber`、`GENERATION`、`DIRDOS_ID`（主键，Edit_Type `½/3`）。
- 请求参数（Tag — 说明，Required）：`StartDateTime`、`EndDateTime`、`MeasurementName`、`StudyName`(Y)、`Generation`、`StudyAnimalNumber`、`PretestAnimalNumber`、`PupNumber`、`DoseStatus`、`GroupNumber`、`DIRDOS_ID`、`LatestDataOnly`、`CountOnly`、`N`、Event_Detail pairs（除 StudyName 外均 N）。
- 响应（父标签 `<DirectDosingInfo>`；化合物父标签 `<ProCompoundInfo>`）：
  - MeasurementName / Count / MeasurementNameForeign / TotalNumDoseQty / LastDoseDateTime / FirstDoseDateTime / DirDosID
  - ProArticleID / ArticleID / ArticleName / ArticleNameForeign / CalculatedDose / SiteOfAdmin / DoseUnits / DoseGiven / DoseTime / DateTaken / CageNumber / GroupNumber / SubGroupNumber
  - SignUser(ID/Name/DateTime/Meaning) / ProPhsID / PmeaProID / DayOfPhase / Session / SessionName / SessionNameForeign / ScheduledFlag / RealTime / EntryDateTime / EntryOperator(ID/RefID) / DoseStatus / DoseStatusName / DoseStatusNameForeign / BodyWeightUsed / BodyWeightUnits / DoseType（1- Measure dose；2- timed dosed）/ NotTakenReason / EntryMethodID / EntryMethodName / EntryMethodNameForeign
  - AnimalID / StudyAnimalNumber / PretestAnimalNumber / ProgenyRefID / PupNumber / PupSex（M, F, U, H）/ PupStudyNum / PupRefNumber / DeleteFlag / EditFlag
  - `<ProCompoundInfo>`：ProCompoundID、CompoundCode、Name、CompoundType、CompoundTypeName、CompoundTypeNameForeign、CompoundForm、CompoundFormName、CompoundFromNameForeign（原文拼写）、Units、Decimal、DoseLevel

### PupClinicalObs（Pup Clinical observation）

- 说明：取幼仔标准临床观察（含观察项与修饰符明细）数据；新增/编辑/删除时触发，只读。
- 触发事件：New clinical observation data for a pup；Edit/Delete clinical observation data for a pup。
- Qualified fields：`OBS_TAKEN`（Y/N）、`NORMAL`（Y=The pup was marked as Normal）。
- Event_Detail：`OBS_TAKEN`、`NORMAL`（限定）、`PRGNREF_ID`、`MeasurementName`、`PretestAnimalNumber`、`PupNumber`、`GENERATION`、`INOB_ID`（主键，Edit_Type `½/3`）。
- 请求参数（Tag — 说明，Required）：`StartDateTime`、`EndDateTime`、`MeasurementName`、`StudyName`(Y)、`Generation`、`StudyAnimalNumber`、`PretestAnimalNumber`、`PupNumber`、`Normal`、`ObsTaken`、`CountOnly`、`N`、`PRGNREF_ID`、Event_Detail pairs（除 StudyName 外均 N）。
- 响应（父标签 `<InlifeObsInfo>`；每个观察父标签 `<ObsDataInfo>`）：
  - MeasurementName / StudyName / Count / MeasurementNameForeign / InObID / Normal / ObsTaken / NotTakenReason / Comment / DateTaken / PupStudyAnmNum / PupRefNumber / CageNumber / GroupNumber / SubGroupNumber
  - SignUser(ID/Name/DateTime/Meaning) / ProPhsID / PmeaProID / DayOfPhase / Session / SessionName / SessionNameForeign / ScheduledFlag / RealTime / EntryDateTime / EntryOperator(ID/RefID) / EntryMethodID / EntryMethodName / EntryMethodNameForeign / AnimalID / StudyAnimalNumber / PretestAnimalNumber / ProgenyRefID / PupNumber / PupSex / DeleteFlag / EditFlag
  - `<ObsDataInfo>`：ObsDataID、StudyCategoryID、CategoryID/Name/(Foreign)、SubCategoryID/StudySubCategoryID/Name/(Foreign)、Severity*、Location*、Size*、Modifier_1..3*(含 TypeInList_1Name/2Name/3Name)、Numerical*、Value、Modifiers、Modifiers2、SignComment

### PupGenMeas（Pup/Litter Generalized measurement）

- 说明：取幼仔/窝广义测量（用户自定义参数）数据；新增/编辑/删除时触发，只读。
- 触发事件：New Pup/Litter Generalized measurement data for a pup/litter；Edit/Delete Pup/Litter Generalized measurement data for a pup/litter。
- Qualified fields：None（无）。
- Event_Detail：`PRGNREF_ID`、`MeasurementName`、`PretestAnimalNumber`、`PupNumber`、`GENERATION`、`GENDAT_ID (multiple, each one is for a user-define parameter)`（主键，Edit_Type `½/3`）。
- 请求参数（Tag — 说明，Required）：`StartDateTime`、`EndDateTime`、`MeasurementName`、`StudyName`(Y)、`Generation`、`StudyAnimalNumber`、`PretestAnimalNumber`、`PupNumber`、`Pass`（Y 只看通过的测量）、`CountOnly`、`N`、Event_Detail pairs（除 StudyName 外均 N）。
- 响应（父标签 `<ParamDataInfo>`）：
  - MeasurementName / Count / GenDatID / MeasurementNameForeign / ProParamID / Abbreviation / ParamName / ParamForeignName / ParamType / ParamUnits / ParamDataType / DataTaken / NotTakenReason / Exclude / ExclusionReason / TextValue / TextName / TextNameForeign / NumericValue / DateTime / LitterSize / DateTaken
  - CageNumber / GroupNumber / SubGroupNumber / SignUser(ID/Name/DateTime/Meaning) / ProPhsID / PmeaProID / DayOfPhase / Session / SessionName / SessionNameForeign / ScheduledFlag / RealTime
  - 其余含 EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、NotTakenReason（**原文重复出现**，"Reason for not taken if the dose status is 2"）、EntryMethodID、EntryMethodName、EntryMethodNameForeign、AnimalID、StudyAnimalNumber、PretestAnimalNumber、ProgenyRefID、PupNumber、PupSex、DeleteFlag、EditFlag

### PupObs（Pup Necropsy Observations）

- 说明：取幼仔尸检观察（大体/新鲜内脏/固定检查/骨骼，按幼仔→组织→发现三层）数据；幼仔观察发现与组织观察新增/编辑、组织清除、发现删除时触发，只读。
- 触发事件：New/Edit Necropsy observation data for a pup（可为 Pup Gross / Pup Fresh Visceral / Pup Fixed Exam / Pup Skeletal Observations）；Pup Tissue Observations：New/Edit；Delete Pup Tissue（Clear tissue for a pup）；Delete Finding（阳性清除或虚线化）。
- Qualified field：`SIGN_OFF`（Y=If the pup passed completion check）。
- Event_Detail：`SIGN_OFF`（限定）、`PMFDAT_ID`（主键）、`PMTFDT_ID`、`PRGNREF_ID`、`GENERATION`、`PupNumber`、`PretestAnimalNumber`、`PupStudyAnmNum`、`MeasurementName`、`FindingListType`（10 – Pup Necropsy Observations）、`TissueListType`（201 Pup Gross / 202 Pup Fresh Visceral / 203 Pup Skeletal / 204 Pup Fixed Visceral Observations）。
- 请求参数（Tag — 说明，Required）：`StartDateTime`、`EndDateTime`、`MeasurementName`、`StudyName`(Y)、`Generation`、`StudyAnimalNumber`、`PretestAnimalNumber`、`PupNumber`、`SignOff`、`CountOnly`、`N`、Event_Detail pairs（除 StudyName 外均 N）。
- 响应（父标签 **`<GrossObsInfo>`（原文如此）**；`<TissueInfo>`、`<FindingInfo>`）：
  - 顶层：MeasurementName / Count
  - 幼仔层：ProgenyRefID、Comment、DeathStatusID/StudyDeathStatusID/DeathStatus(Foreign)、DeathProPhaseID/DeathPhase(Foreign)、DayOfPhase、DeathTime、Approximate、PupNumber、PupSex、CageNumber、GroupNumber、SubGroupNumber、PupStudyAnmNum、PupRefNumber、AnimalID、StudyAnimalNumber、PretestAnimalNumber
  - `<TissueInfo>`：MeasurementNameForeign、MEADAT_ID、MeasurementType、MeasurementTypeName、PMTissueFindID、ProTissueID、TissueID、NormalPhrase、TissueName(Foreign)、TissueDashed、TissueComment、`DateTaken*`、ProPhsID、PmeaProID、`DayOfPhase**`、ScheduledFlag、RealTime、Entry*/Sign*/DeleteFlag/EditFlag/EntryMethod*
  - `<FindingInfo>`：FindingDataID、FindingDashed、StudyFindingID、FindingName(Foreign)、PMORGFDREF_ID、OrgFindingName(Foreign)、OrgLongForm(Foreign)、OrgTissueName(Foreign)、FindingComment、Severity*、Location*、Sublocation*、Size*、Modifier_1..6*、Numerical*、Review*、Classification*、Entry*/Sign*
  - 注意（原文脚注）：`*` 同 FetalObs — 骨骼/固定报告的 DateTaken 为尸检后入库日；`**` TissueInfo 的 DayOfPhase 为空。

### LitterWeight（Litter Weights）

- 说明：取窝重数据（含 pup 计数与类型：整窝/雄/雌）；由 Litter Generalized measurement 录入窝重时触发，只读。
- 触发事件：New litter weight entered from Litter Generalized measurement data entry；Edit/Delete litter weight from Litter Generalized measurement。
- Qualified fields：None（无）。
- Event_Detail：`MeasurementName`、`PretestAnimalNumber`、`GENERATION`、`LITWGT_ID`（主键，Edit_Type `½/3`）。
- 请求参数（Tag — 说明，Required）：`StartDateTime`、`EndDateTime`、`MeasurementName`、`StudyName`(Y)、`Generation`、`StudyAnimalNumber`、`PretestAnimalNumber`、`CountOnly`、`N`、Event_Detail pairs（除 StudyName 外均 N）。
- 响应（父标签 `<LitterWeightInfo>`）：
  - MeasurementName / Count / MeasurementNameForeign / LitterWeightID / ProParamID / Abbreviation / ParamName / ParamForeignName / RawWeight / StorageUnit / Exclude / ExcludeReason
  - NumberPup / NumberPupMale / NumberPupFemale / Types（1- Litter weight；2 – Male litter weight；3 – Female litter weight）/ TypesName / TypesNameForeign / DateTaken
  - CageNumber / GroupNumber / SubGroupNumber / SignUser(ID/Name/DateTime/Meaning) / ProPhsID / PmeaProID / DayOfPhase / Session / SessionName / SessionNameForeign / ScheduledFlag / RealTime
  - 其余含 EntryDateTime、EntryOperator、EntryOperatorID、EntryOperatorRefID、EntryMethodID、EntryMethodName、EntryMethodNameForeign、AnimalID、StudyAnimalNumber、PretestAnimalNumber、DeleteFlag、EditFlag

### DamPupData（Dam Pup Cross Reference data）

- 说明：取母鼠-幼仔交叉引用数据（母鼠信息 + 每个幼仔死亡/适应/给药/下一代分配 + 每个幼仔的测量分配）；Parturition、评性别、评号、标记死亡、下一代分配、测量分配、寄养事件触发，只读。
- 触发事件：Parturition（活/死幼仔记录创建）、Assign Pup Sex、Assign Pup Number、Mark Pup Dead、Assign Pup to Next generation、Assign Pup to measurements、Foster Pup（均在 Generalized measurement 或 Study Tools 中）。
- Qualified field：事件为 Parturition 时 `PARTURITION_STATUS`（0=Not Started / 1=In Progress / 2=Complete）；非 Parturition 则 None。
- Event_Detail（两套）：Parturition：`PARTURITION_STATUS`（限定，0/1/2）、`MeasurementName`、`PretestAnimalNumber`、`GENERATION`、`PARSES_ID`（主键）；非 Parturition：`PRGNREF_ID`、`MeasurementName`、`PupNumber`（均 Informational，无主键行）。
- 请求参数（Tag — 说明，Required）：`StartDateTime`（mark pup dead 起始，含）、`EndDateTime`（不含）、`StudyName`(Y)、`Generation`、`StudyAnimalNumber`、`PretestAnimalNumber`、`PupNumber`、`ParturitionStatus`（1 – In progress；2 – Complete；缺省全部）、`CountOnly`、`N`、Event_Detail pairs（除 StudyName 外均 N）。
- 响应（父标签 `<DamPupInfo>`；每个幼仔父标签 `<PupDataInfo>`；每个测量分配父标签 `<PupMeasDataInfo>`）：
  - 母鼠层：StudyName / Count / CageNumber / GroupNumber / SubGroupNumber / AnimalID / StudyAnimalNumber / PretestAnimalNumber / SpeciesRefID / StrainRefID / StrainName(Foreign) / SpeciesName(Foreign) / SupplierRefID / SupplierName / SupplierCode / SupplierLocation / NumGeneration / ParturitionDate
  - `<PupDataInfo>`（每个幼仔）：ProgenyRefID、PupStudyAnmNum、PupRefNumber、PupNumber、PupSex、PupIdentifyDT、DeathStatusID/DeathStatusRefID/StudyDeathStatusID/DeathStatus(Foreign)、ProPhaseID、DeathPhase(Foreign)、DayOfPhase、DeathTime、Approximate、Comment、DeathType、Scheduled、ScheduledFlag、DeathStatusForeign（含 IncludeComplete 说明）、DeathEntryDateTime、DeathEntryOperator(ID/RefID)、LastDoseDateTime、FirstDoseDateTime、NextGenPretestNumber、FosteredFromDamID、FosteredFromDamStudyNumber、FosteredFromDamPretestNumber、FosteredFromDateTime
  - `<PupMeasDataInfo>`（每个幼仔每个测量分配）：PupMeasAssignID、PmeaProID、MeasurementName(Foreign)、DateTaken、ProPhsID、DayOfPhase
  - 注意：`DeathStatusForeign` 在原文响应表中出现两次。

### MatingStatus（Mating Status）

- 说明：取母鼠交配状态数据（是否交配、配偶信息）；Assign Dam Mate 事件触发，只读。
- 触发事件：Mark animal not mated during mating data entry；Assign animal to Gestation phase during animal mating data entry；Input Mate/Edit/Delete Mate in study tools。
- Qualified field：`STATUS`（1=Mated / 2=Not Mated）。
- Event_Detail：`½TATUS`（原文如此，实为 `STATUS`；取值 `½`＝1）、`PretestAnimalNumber`、`GENERATION`、`MATEST_ID`（主键，Edit_Type `½/3`）。
- 请求参数（Tag — 说明，Required）：`StartDateTime`、`EndDateTime`、`StudyName`(Y)、`Generation`(Y)、`StudyAnimalNumber`（Dam）、`PretestAnimalNumber`（Dam）、`Status`（1-Mated, 2- Not Mated；缺省全部）、`CountOnly`、`N`、Event_Detail pairs。
- 响应（父标签 `<MatingStatusInfo>`）：
  - StudyName / Generation / Count / `½Status`（原文如此，实为 Status；1-Mated, 2- Not Mated）/ StatusName / StatusNameForeign / StatusDate / MateText / MateAnimalID / MateStudyName（原文被截断为 "Mate’"）/ MateStudyAnimalNumber / MatePretestAnimalNumber
  - CageNumber / GroupNumber / SignUser(ID/Name/DateTime/Meaning) / ProPhsID（studytools 录入时可为 null）/ DayOfPhase（同上）/ EntryDateTime / EntryOperator(ID/RefID) / AnimalID / StudyAnimalNumber / PretestAnimalNumber / DeleteFlag / EditFlag

---

## 十三、Pharmacy（未实现占位）

- 说明：**未实现** — 原文仅一行：`To be determined in a subsequent functional design specification.`（无 API 条目、无请求/响应）。
- 触发事件：无/未实现。
- 请求参数 / 响应：无。

---

## 十四、杂项类

### AgeRange（Age Range Information）

- 说明：随时可调用，取年龄范围（age range）相关信息，只读。
- 触发事件：无/未实现（文档未列 Event_Detail）。
- 请求参数（Tag — 说明，Required）：
  - `ParamName` — 一个或多个参数名（N）
  - `StrainName` — 一个或多个动物品系名（N）
  - `SpeciesName` — 动物种属名（N）
  - `TissueName` — 一个或多个组织名（N）
  - `ParamType` — 参数类型（若提供 ParamName 则忽略 ParamType）（N）
  - `N` — 最大记录数（N）
- 响应（父标签 `<AgeRangeInfo>`）：
  - ParamID / Abbreviation / ParamName / ParamNameForeign
  - TissueRefID / TissueAbbr / TissueName / TissueNameForeign
  - StrainRefID / StrainName / StrainNameForeign
  - SpeciesRefID / SpeciesName / SpeciesNameForeign
  - AgeID / AgeStart / AgeStartUnits / AgeEnd / AgeEndUnits / AgeStoredUnits
  - EntryDateTime / EntryOperator / EntryOperatorID / EntryOperatorRefID

### Measurement（Measurement Information）

- 说明：随时可调用，取测量（measurement）主数据；若请求提供 StudyName 则取该专题协议测量信息，只读。
- 触发事件：无/未实现。
- 请求参数（Tag — 说明，Required）：
  - `StudyName` — 专题名（N）
  - `Types` — 1=colony，2 或 null=study（N）
  - `Generation` — 多代研究代数，单代 0；缺省为全部代（N）
  - `MeasurementType` — 一个或多个测量类型（N）
  - `MeasurementName` — 一个或多个测量名（N）
  - `SubjectID` — 一个或多个测量 subject ID（N）
- 响应（父标签 `<MeasurementInfo>`）：
  - ProtocolID / StudyName / MeaDatID / ActiveFlag / MeasurementName / MeasurementName Foreign / MeasurementType / TypeName / TypeNameForeign
  - CategoryID / Category / CategoryForeign / SOP / SessionLockTime / SessionTerminateTime / ReEntryTime
  - SchFreq / SchFreqName / SchFreqName Foreign / SubjectID / Subject / SubjectForeign / FileEntry / ConfigFileName / Comment
  - EntryDateTime / EntryOperator / EntryOperatorID / EntryOperatorRefID
  - 注意：`MeasurementName Foreign` 与 `SchFreqName Foreign` 原文 tag 名含空格。

### Parameter（Parameter Information）

- 说明：随时可调用，取参数（parameter）主数据列表，只读。
- 触发事件：无/未实现。
- 请求参数（Tag — 说明，Required）：
  - `ParamType` — 一个或多个参数类型索引（N）
  - `NumericalOnly` — Y 只看数值型参数（N）
  - `ActiveFlag` — Y 只看有效参数（N）
  - `SampleParam` — Y 关注临床病理样本结果参数（含用户自定义参数与细胞计数参数）（N）
- 响应（父标签 `<ParameterInfo>`）：
  - ParamID / ParamName / ParamNameForeign / Abbreviation / ParamType / TypeName / TypeNameForeign
  - PrimitiveType / PrimitiveTypeName / PrimitiveTypeForeign / StorageUnit / ActiveFlag
  - EntryDateTime / EntryOperator / EntryOperatorID / EntryOperatorRefID

### Tissue（Tissue Information）

- 说明：随时可调用，取组织（tissue）主数据列表，只读。
- 触发事件：无/未实现。
- 请求参数（Tag — 说明，Required）：
  - `ActiveFlag` — Y 只看有效组织（N）
  - `ApprovalFlag` — Y 只看已批准组织（N）
- 响应（父标签 `<TissueInfo>`）：
  - TissueID / TissueRefID / ActiveFlag / ApprovalFlag / TissueName / TissueNameForeign / TissueAbbr / Sex / Paired / PairedWeightFlag / DefaultTissue / ProcessFlag
  - EntryDateTime / EntryOperator / EntryOperatorID / EntryOperatorRefID

### InterfaceTransmission（Interface successful transmission report）

- 说明：随时可调用，取成功传输报告（来自 PTS_REPORT.PTS_INTEGRATION_REPORT），只读。
- 触发事件：无/未实现。
- 请求参数（Tag — 说明，Required）：
  - `**StudyNameSum` — Y/N，Y 表示按 StudyName 汇总（N）
  - `TransDateFrom` — 传输开始日（含）（Y）
  - `TransDateTo` — 传输结束日（不含）（N）
  - `**MessageTypeSum` — Y/N，Y 表示按 Message type 汇总（N）
- 响应（父标签 `<TransmissionInfo>`）：
  - TransID / TransDate / StudyName / StudyAnimalNumber / SystemName / MessageType
  - InsertCount / UpdateCount / DeleteCount / TotalCount — 该专题该消息类型的插入/更新/删除/合计条数
  - SiteCode / SiteName / EventID
  - 脚注 `**`（原文）：若请求含 MessageTypeSum、StudyNameSum，则 Insert/Update/DeleteCount 为每个交易日期下按 MessageType 与 StudyName 的计数，结果按 TransDate、MessageType、StudyName 排序。

### InterfaceError（Interface error transmission error report）

- 说明：随时可调用，取错误传输报告（来自 PTS_REPORT.PTS_INTEGRATION_ERROR），只读。
- 触发事件：无/未实现。
- 请求参数（Tag — 说明，Required）：
  - `StudyName` — 专题名（N）
  - `ErrorDate From` — 传输错误开始日（含）；**原文 tag 名含空格**（Y）
  - `ErrorDateTo` — 传输错误结束日（N）
  - `StudyAnimalNumber` — 专题动物号（N）
- 响应（父标签 `<TransmissionInfo>`）：
  - ErrorID / EventID / ErrorDate / StudyName / StudyAnimalNumber / SystemName / MessageType / Message / SourceVal / TargetVal / SiteCode / SiteName / EventID（**原文 EventID 重复出现**）

### ReportConfiguration（Report Configuration API）

- 说明：随时可调用，取站点最新报表配置（来自 REPORT_CONFIGURATION 与 SITE 表），只读。
- 触发事件：无/未实现。
- 请求参数（Tag — 说明，Required）：
  - `SiteName` — 站点名（N）
  - `SiteID` — 站点索引（N）
- 响应（父标签 `<ReportConfigureInfo>`）：
  - SiteID / SiteName / CompanyName / Country / State / ZipCode / City / Address / TimeFormat / TimeZoneFormat / ConvertTimeZone

---

## 十五、错误响应示例（与第五节同源）

三种失败响应格式（均为 `pts_rs_failure`）：

### Unsupported request（不支持的请求）

- 说明：在 Device access 或 Login 验证通过之前请求 API 功能，或请求了不支持的 API 时返回。
- 响应（原文）：
  ```xml
  <?xml version="1.0" encoding="UTF-8"?>
  <PTS>
  <Doctype>pts_rs_failure</Doctype>
  <ErrorType>1</ErrorType>
  <Key>213002</Key>
  <FailureMessage>Invalid request string</FailureMessage>
  </PTS>
  ```

### Privilege error（权限错误）

- 说明：用户无 API Output 权限，或 Application Program Interface 测量类型无可用 license 时返回。
- 响应（原文，**无 FailureMessage 标签**）：
  ```xml
  <PTS>
  <Doctype>pts_rs_failure</Doctype>
  <ErrorType>0</ErrorType>
  <Key>9</Key>
  </PTS>
  ```

## 十六、文档修订记录（Issue 1~15 摘要）

> 原文为长变更记录表（Date | Issue | Issued / By | Description | Version）。此处按 Issue 归纳（不逐行罗列），完整逐行版本见原文第 7275~7505 行。

| Issue | 日期范围 | 主要变更（含涉及 API） | Version |
|---|---|---|---|
| 1 | 2012-03-15 起 | 初版；Protocol/Animal info 的事件描述；FoodConsumptionInfo 加 Spilled；AnimalData 加 DeathStatusRefID、SpeciesRefID、ReceiptDate、OrderNumber、ColonyName、OrigColonyName、NumGeneration、CurrentLocation、ReproStudyFlag、DamParturitionDate；BodyWeight 加 Alternate keys/Generation、BodyWeightType；ProParameter/ProtocolInfo（PlannedSTDate/PlannedEnDate/SupplierLocation/PlannedPHSTDate）更新；ProArticle 加 StudyName、PROART_ID、CompoundCASNo、Generation、ScheduledDays、Long Name/Biologic、StartTP；MassTracking 加 StudyName、descriptor/location id、converge mass number、alternate keys（并把 'Discriptor…' 更正为 'Descriptor…'）；StudySampleResults/SampleCollection/SampleObs 加 alternate keys 与列；FoodConsumption 加 alternate keys、CageNumber 更正、FF_EF_ID 请求参数、AnimalIDs/StudyAnimalNumbers；CellMorphology 更新；AnimalCage 更新与 tag 移至顶层；ClinicalObs 加 Meadat_ID、PhaseName(Foreign)、SeverityLevel、TimePointRefText/ElapseTime；StudyEventUpdate 加 status code 3/4；InterfaceTransmission/InterfaceTransmissionInsert/InterfaceError/InterfaceErrorInsert 新增；ProArtShortText 新增；OrganWeight 加 ORGWGT_ID 请求；MicroObs 加 PMTFDT_ID/PMFDAT_ID 请求与响应 tag、Chronicity、OrigNeoplasmType、OrgFindingDataID、SkullTissueName/SkeletalExamCD（后于 Issue 9 撤回）；FetalObs 加 ReviewModUsage/PMTFDT_ID/PMFDAT_ID/MeasurementType/PMFDREF/MEADAT_ID；PupBodyWeight/PupObs/PupClinicalObs 加 PupStudyNum/PupRefNumber/PupStudyAnmNum；DamPupData 加 NumGeneration/SpeciesRefID/StrainRefID/SupplierRefID/ParturitionDate/PupRefNumber/PupStudyAnmNum/DeathStatusRefID/PupIdentifyDT、pup death tags、FirstDoseDateTime/LastDoseDateTime；Generation/Types/StudyName 在请求与响应中的统一补齐（AnimalData、StudyAnimalPhase、StudyAnimalCage、BodyWeight、StudySampleResults、SampleCollection、SampleObs、CellMorphology、ClinicalObs、FoodConsumption、MassTracking、DirectDosing）；DirectDosing 加 TotalDoseQty、FirstDoseDate、LastDoseDateTime、SiteOfAdmin、TimePointRefText、ReferenceTime、Duration、ElapseTime、EndDateTaken、Biologic、LongName、LotBatch 业务逻辑；MatingStatus 加 MateStudyName；AnimalComment 加签名信息、MeasurementType、ProPhsID/PhaseName、ReqType；TissueStatus 加 MeasurementTypeName、TissueID、StatusTypes、PupStudyAnmNum/PupRefNumber、Gross Observation 组织状态 | 1（后续 7.4.x） |
| 2 | 2013-02-04 起 | 删除类事件拆分为独立事件：Sample collection（Delete Sample collection）、Clear Sample observation、Gross observation（Delete Finding、Gross Tissue observations）、Tissue Status（Delete Tissue Status，加 PMTSTA_ID 请求）、Micro observation（Micro Tissue observations、Delete Finding）、Correlation（Delete Correlation、后撤回）、Organ Weights（Delete）；MicroObs/GrossObs 响应加 originating tissue/finding tags、modifier reference index、EarliestMassDT 算法；Correlation API 请求/响应参数、GrossFindingDataID/MicroFindingDataID 加入事件明细与 GrossObs/MicroObs/Correlation 请求；OvaryExam/Csection 加 CorporaLutea left/right/total；Protocol Special Privilege 事件；SampleObsDescriptorID/SampleObsDescriptorText 加入 Sample Observation 事件；InstanceNum 算法；StudySampleResult 的 IncludeProtDefault（后撤回） | 2 |
| 3 | 2013-03-11 起 | Edit Gross/Micro Observation 事件变更、Delete Finding 事件描述变更；ProParmeter API 更新；Instance number 变更（Delete Finding 事件、MicroObs API、Correlation 事件明细）**被推迟且不实施** | 3 |
| 4 | 2013-04-29 起 | ProNecSchedule API 新增（后加 TimeToSacrifice、Necropsy Name/ForeignName、SubGroupNumber）；ProPhase 请求加 ProPhaseID、NonAnimal tag；Delete Protocol Phase Information 事件拆出；TissueStatus 请求加 TissueName、Micropathology/Tissue Status 事件加 TissueName；IndirectDosing/FoodConsumption 澄清 FF_EF_ID（IndirectDosing 加 LongName、Biologic、DayOfPhaseFF、ScheduledFlagFF/ScheduledFlag）；ReportConfiguration API 新增；ClinicalObs/CellMorphology 加数值型 modifier 单位与 Modifiers 支持；消息概述章节；PlannedSTDate 按 IgnorePhase 名更新；MicroObs SeverityRefID 注释 | 4 |
| 5 | 2014-05-09 起 | UterineExam 的 ParamDataInfo 加参数单位与小数位、请求加 UTREF_ID；FetalObs 的 TissueInfo 加 TissueID/MeasurementTypeName/NormalPhrase、FindingInfo 加 Modifiers/Modifiers2/NormalPhrase；**ProgenySex API 新增**；EstrusCycleMon、MatingMon 响应加 StudyName/Generation；EVENT 表加 STATUS2 列（StudyEvent/StudyEventUpdate 加 Status2/NewStatus2）；SupervisoryReview 加入 Sample Collection 与 Delete 事件明细；SampleTubeKey 加入样本采集事件明细；PupBodyWeight 请求加 IncludeParameter/BW_ID 与响应参数；ProDoseGroup 加 PGRPNM_ID 请求与 PretestPhEx；Fetal/Pup Tissue observations 与 Delete Finding 事件；AnimalComment 事件启用成体动物与请求响应更新；Mark Colony/Study Animal Complete（仅 Study）；ClinicalObs 加体温参数响应；PupDirectDosing 更新；ProArticle 事件改名 "Protocol Dosing Article Information"；Generation 请求参数定义；Estrus Observation 引用 Clinical Observations；PupClinicalObs 加 TypeInList_1/2/3Name、Modifiers/Modifiers2；Edit Protocol 含 rename studies；StudyFocus 加入 Directdosing/ClinicalObs/GrossObs/MicroObs/TissueStatus；MicroObs/GrossObs 的 Modifiers2 排除 Severity 与 Relation to Death；FoodConsumption CageNumber 支持多笼；**FullFeeder API 新增**（仅返回未称重的满料盒） | 5 |
| 6 | 2017-08-22 | Approved Issue 6 | 6 |
| 7 | 2017-11-07 起 | TissueStatus 加 PupStudyAnmNum/PupRefNumber；GenMeas 加 position/method/Consciousness state/baseline flag/dosing/time point tags、ColonyFlag、StudyDataFlag、Scheduled Days、TimeTaken；BodyWeight/StudySampleResult/ClinicalObs/CellMorphology 加 ColonyFlag、BLFlag、StudyDataFlag；ProtocolInfo 加 study sponsor 与 sponsor study number | 7.4.1/7.4.2 |
| 8 | 2018-05-01 | Approved Issue 8 | 7.4.2 |
| 9 | 2018-05-14 起 | StudyDataFlag 更新（CellMorphology、BodyWeight、GenMeas、StudySampleResult、ClinicalObs）；撤回 MicroObs 的 SkullTissueName/SkeletalExamCD；GenMeas 加 TimeTaken | 7.4.0/7.4.2 |
| 10 | 2018-08-03 起 | TissueStatus 事件与 API 支持 Gross Observation 组织状态；SampleCollection 加 ElapseTime/TimePointRefTex/TimePointText/DateTimeOfDose、SampleTubeAliquotData 响应（含分析样本类型）；GenMeas 使用 GEN_MEAS_SESSION_DETAILS.date_time_taken；Study animal information 与 Body Weights 的触发加 PROREF_ID 与请求参数 | 7.4.3 |
| 11 | 2019-02-25 起 | **ProRelFinding（Protocol Relevant Finding information）章节新增**；移除空白页与语法修正 | 7.5.0 |
| 12 | 2019-08-07 起 | ProRelFinding 加 Session/SessionName | 7.5.0 |
| 13 | 2019-11-08 起 | Edit Study Finding、Edit Study Lexicon 触发加入 Gross/Micro observations 事件；ProSubgroup 响应加 GroupSubgroupInfo | 7.5.1 |
| 14 | 2020-04-14 起 | BodyWeight/TerminalBodyWeight、SampleCollection 加 FastingFlag 与 Fasting Desc；**Study Baseline data 章节新增**（触发与 API）；BodyWeight/GenMeas/StudySampleResult 的 BLFlag 澄清；更新版权 | 7.5.2 |
| 15 | 2021-04-02 起 | 更新版权；MicroObs 响应加 SummaryTissueType、SummaryTissueType（生殖组织性成熟与周期） | 7.5.3 |

---

## 附：原文异常清单（调用前必读）

1. **PDF 提取伪影**（全局）：`½` 常代表 1（如 `½/3`＝1/2/3、`DO½STATUS`＝DOSE_STATUS、`½STATUS`＝STATUS、`½TATUS`＝STATUS、`½Status`＝Status、`t½record`＝the record）；`”=”` 是 `="` 的提取损坏；个别 tag 名内有多余空格（如 `SampleCollData` 表中的 `SmpCondName Foreign`、`TypeText Foreign`、`CompoundFromNameForeign`、`MeasurementName Foreign`、`SchFreqName Foreign`）。
2. **父标签与实现不符之处**（原文如此，未改）：MicroObs 与 FetalObs/PupObs 的响应父标签写作 `<GrossObsInfo>`；ProNecSchedule 响应父标签写作 `<ProScheduleInfo>`；AnimalCage 响应标题写作 "Animal phase assignment data"。
3. **请求参数表 Required 列错位**：StudySampleResult、SampleCollection、SampleObs 的 `Generation` 行、ProductAdmin 的 `PRADMIN_ID` 行、FetalObs 的 `PMTFDT_ID` 行（Required 列为空或错位）。
4. **响应表内重复行**：ProParameter `StorageUnit` ×2；Csection `PregnancyStatusID` ×2；DirectDosing `Tolerance` ×2；InterfaceError `EventID` ×2；PupGenMeas `NotTakenReason` ×2；DamPupData `DeathStatusForeign` ×2；StudySampleResult 示例中 `Session` 行括号未闭合。
5. **PupBodyWeight 的 XML Schema 与示例段**（第 5805~6129 行）提取损坏最严重：`name=”=”X””`、`<xsd:element name=”PmeaProID”=”PmeaProID” .../>`、示例中 `<PMeaProIDPmeaProID>32</PMeaProIDPmeaProID>`。
6. **文档自身的拼写错误**（保留原文）：`IntefaceTransmissionInsert` / `IntefaceErrorInsert`（实际 API 名）、`mciropathology`、`protilly`、`partilly`、`relateion`、`origninating`、`Acitve`、`Measurment`、`beservation`（MassTracking 标题 "Animal Mass Tracking bservation"）、`Recievie`、`plese refer`、`informaiton`。
7. **引用式段落**（无独立请求/响应表，需回看被引章节）：TermBodyWeight → 12.2.5.1 Body Weights；GrossObs → 12.2.8.1 Micro Observation；EstrusObs → Animal Standard Clinical Observations。
8. **未实现/占位**：12.2.9 Pharmacy（"To be determined in a subsequent functional design specification."）；StudySampleResult 响应未标注父标签名。
9. **Amendment 表中标注"推迟不实施"**：Issue 3 的 Instance number 相关变更（Delete Finding 事件、MicroObs API、Correlation 事件明细）；Issue 2 的 Delete Correlation event 与 EarliestMassDT（于 Correlation 事件明细中）后被移除。
