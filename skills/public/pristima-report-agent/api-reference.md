# Pristima Report Server API 参考

Base URL：`http://10.0.27.60:8890`。以下接口均使用 `POST` 和 `Content-Type: application/json`。服务端代码入口为 `info/modules/report_project/views.py`；本文件记录 Agent 所需的最小调用契约。

## 查询专题报表树

`POST /report_project/GetPTSReportTree`

```json
{"study_number":"A2026002-GA015-02"}
```

成功响应的 `errno` 为 `0`，`data` 包含 `study_number`、`proref_id`、`tree_data` 和 `checked_all_data`。`checked_all_data` 是当前专题可勾选的报表叶子节点列表。每个节点的 `title` 是业务标题，`report_name`、`rpt_data_type`、`rptformat_id` 是生成接口需要的内部身份。树节点还可能包含 `measurement_selection` 与 `report_selection`，表示支持对应选项；它们不等于用户必须缩小范围。树返回的 `proref_id` 仅说明此次报表树查询使用的专题记录。

服务端报表树在仅传 `study_number` 时查询 Pristima Oracle 的 `PRO_REFERENCE`，条件为 `study_number = :study_number`，按 `PROREF_ID DESC` 取首条；若调用方已经提供 `proref_id`，树直接使用该值。Agent 通常只传专题编号，不为生成任务另外查 ID，也不把树返回的 ID 放进生成请求。按 ID 降序取首条只代表树服务当前实现，不能据此断言它是生成数据所用的最新有效记录。

## 预览表格或生成 PDF

`POST /report_project/HandleReportProject`

请求体必须包在 `config_info` 中。下方身份字段的值应从**本专题树的同一个节点**读取；占位文字不能直接发送：

```json
{
  "config_info": {
    "study_number": "A2026002-GA015-02",
    "report_name": "该节点的 report_name",
    "rpt_data_type": "该节点的 rpt_data_type",
    "rptformat_id": "该节点的 rptformat_id",
    "render_type": "pdf"
  }
}
```

`render_type=table` 返回 JSON，成功时 `errno=0`，报表数据在 `data` 中。`render_type=pdf` 成功时返回 `application/pdf` 文件流，文件头应为 `%PDF-`；失败时可能返回 JSON 错误。接口没有要求把报表树的 `proref_id` 加到生成请求中。

当前 Body Weight、Standard Clinical Observations、Generalized Measurement 和 Organ Weight 处理器各自从 `study_number` 进入取数链，再调用 Doris 的 `get_proref_id_by_study_number_doris` 取得业务数据 `PROREF_ID`；该查询按专题编号过滤 `latest='Y'` 且 `types=2` 或空。各报表取数、统计、审计及 Measurement 条件仍由对应处理器负责。树查询和生成查询来源、过滤规则不同，Agent 不能假设两个 ID 相等；若用户需要严格核对专题版本，应报告这一服务端边界，而不是自行覆盖某个 ID。

默认不传筛选条件。用户明确要求筛选时，按该报表支持的 Selection 键名构造 `config_info.report_tables.table_1.select_option`，并让预览与 PDF 使用完全相同的条件。例如用户明确指定动物 `1M003`，且已经核对它属于该专题时：

```json
{
  "report_tables": {
    "table_1": {
      "select_option": {
        "StudyAnimalNumber": "1M003"
      }
    }
  }
}
```

这段对象可保存为 UTF-8 JSON 文件，并传给脚本的 `--config-file`；脚本会把它并入 `config_info`。不同报表的可用 Selection 键可能不同，不能仅凭这一个示例推断其他字段。

### 显示已有签名

用户明确要求报表提供或显示已有电子签名时，对支持签名展示的报表在 `config_info` 顶层传入 JSON 布尔值 `"With_Signature": true`。不要放进 `report_tables.table_1.select_option`。

```json
{
  "config_info": {
    "study_number": "A2026002-GA015-02",
    "report_name": "body_weight",
    "rpt_data_type": "1001",
    "rptformat_id": "104",
    "render_type": "pdf",
    "With_Signature": true
  }
}
```

当前明确支持该开关的是 `body_weight / 1001 / 104` 和 `clinical_observation_raw / 1005 / 112`。未传时默认关闭；开启后也只展示源数据中已经存在的签名人、签名时间和签名含义，不会创建新签名。其他报表是否支持必须单独核对，不能默认把该参数视为全局能力。

## 错误判定

- HTTP 调用失败：报告网络或服务错误，最多自动重试一次。
- JSON 响应 `errno != 0`：报告接口 `errmsg`，不要把响应当成结果。
- PDF 请求返回 JSON、HTML、空字节或非 `%PDF-` 文件头：判定生成失败，不写入 `.pdf`。
- 已有输出文件：默认保留原文件，另选文件名；不自动覆盖。
