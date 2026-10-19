"""查询 Pristima 专题报表树，并预览或保存现有报表。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_URL = "http://10.0.27.60:8890"
TREE_PATH = "/report_project/GetPTSReportTree"
REPORT_PATH = "/report_project/HandleReportProject"
CORE_KEYS = {"study_number", "report_name", "rpt_data_type", "rptformat_id", "render_type"}


class ClientError(Exception):
    """可向 Agent 展示的客户端或接口错误。"""


def post_json(base_url: str, path: str, payload: dict[str, Any], timeout: float) -> tuple[int, str, bytes]:
    """发送 POST JSON，并保留 HTTP 错误响应体。"""
    request = Request(
        base_url.rstrip("/") + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8", "Accept": "application/json, application/pdf"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read()
    except HTTPError as error:
        return error.code, error.headers.get("Content-Type", ""), error.read()
    except (URLError, TimeoutError, OSError) as error:
        raise ClientError(f"无法连接报表服务：{error}") from error


def api_json(status: int, body: bytes) -> dict[str, Any]:
    """解析并检查 Report Server 的 JSON 业务响应。"""
    try:
        result = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ClientError(f"接口未返回有效 JSON（HTTP {status}）") from error
    if not isinstance(result, dict):
        raise ClientError("接口 JSON 顶层不是对象")
    if not 200 <= status < 300 or str(result.get("errno", "")) != "0":
        message = str(result.get("errmsg") or "接口返回错误")
        raise ClientError(f"{message}（HTTP {status}，errno={result.get('errno')}）")
    return result


def report_identity(args: argparse.Namespace) -> dict[str, str]:
    """从命令行收集同一报表节点的身份字段。"""
    return {
        "study_number": args.study_number,
        "report_name": args.report_name,
        "rpt_data_type": args.rpt_data_type,
        "rptformat_id": args.rptformat_id,
    }


def report_config(args: argparse.Namespace, render_type: str) -> dict[str, Any]:
    """构造生成接口的 config_info，拒绝附加配置覆盖核心身份。"""
    config: dict[str, Any] = {**report_identity(args), "render_type": render_type}
    if args.config_file:
        config_path = Path(args.config_file).expanduser().resolve()
        try:
            extra = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ClientError(f"无法读取附加配置 {config_path}：{error}") from error
        if isinstance(extra, dict) and "config_info" in extra:
            extra = extra["config_info"]
        if not isinstance(extra, dict):
            raise ClientError("附加配置必须是 JSON 对象")
        conflicts = CORE_KEYS.intersection(extra)
        if conflicts:
            raise ClientError(f"附加配置不能覆盖报表身份：{', '.join(sorted(conflicts))}")
        config.update(extra)
    if args.generated_by is not None:
        config["generated_by"] = args.generated_by.strip()
    return config


def output_file(value: str, suffix: str) -> Path:
    """检查输出路径，并保留已有文件。"""
    target = Path(value).expanduser().resolve()
    if target.suffix.lower() != suffix:
        raise ClientError(f"输出文件必须使用 {suffix} 扩展名")
    if target.exists():
        raise ClientError(f"输出文件已存在：{target}")
    return target


def save_bytes(target: Path, body: bytes) -> None:
    """以独占模式保存非空响应，避免覆盖已有文件。"""
    if not body:
        raise ClientError("响应内容为空")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(body)
    except OSError as error:
        raise ClientError(f"无法保存 {target}：{error}") from error


def list_reports(args: argparse.Namespace) -> dict[str, Any]:
    """查询专题可用报表，返回 Agent 需要的叶子身份。"""
    status, _, body = post_json(
        args.base_url, TREE_PATH, {"study_number": args.study_number}, args.timeout
    )
    response = api_json(status, body)
    data = response.get("data")
    if not isinstance(data, dict):
        raise ClientError("报表树缺少 data 对象")
    if str(data.get("study_number", "")).upper() != args.study_number.upper():
        raise ClientError("报表树返回的专题编号与请求不一致")
    leaves = data.get("checked_all_data")
    if not isinstance(leaves, list):
        raise ClientError("报表树缺少 checked_all_data 列表")
    reports = []
    for leaf in leaves:
        if not isinstance(leaf, dict):
            raise ClientError("报表树包含无效叶子节点")
        identity = {key: leaf.get(key) for key in ("title", "report_name", "rpt_data_type", "rptformat_id")}
        if any(value in (None, "") for value in identity.values()):
            raise ClientError("报表树叶子节点缺少报表身份")
        reports.append(identity)
    return {
        "study_number": data["study_number"],
        "tree_proref_id": data.get("proref_id"),
        "count": len(reports),
        "reports": reports,
    }


def table_report(args: argparse.Namespace) -> dict[str, Any]:
    """获取表格 JSON 并保存到 Agent 指定的路径。"""
    config = report_config(args, "table")
    status, _, body = post_json(args.base_url, REPORT_PATH, {"config_info": config}, args.timeout)
    response = api_json(status, body)
    target = output_file(args.output, ".json")
    save_bytes(target, json.dumps(response, ensure_ascii=False, indent=2).encode("utf-8"))
    return {"report": report_identity(args), "output": str(target), "type": "table"}


def pdf_report(args: argparse.Namespace) -> dict[str, Any]:
    """验证 PDF 响应并以独占模式保存。"""
    config = report_config(args, "pdf")
    status, content_type, body = post_json(args.base_url, REPORT_PATH, {"config_info": config}, args.timeout)
    mime = content_type.split(";", 1)[0].strip().lower()
    if not 200 <= status < 300 or mime != "application/pdf" or not body.startswith(b"%PDF-"):
        try:
            api_json(status, body)
        except ClientError as error:
            raise ClientError(f"PDF 生成失败：{error}") from error
        raise ClientError(f"接口未返回有效 PDF（HTTP {status}，Content-Type={content_type or '空'}）")
    target = output_file(args.output, ".pdf")
    save_bytes(target, body)
    return {"report": report_identity(args), "output": str(target), "type": "pdf", "bytes": len(body)}


def parser() -> argparse.ArgumentParser:
    """创建 list、table 和 generate 三个命令。"""
    main = argparse.ArgumentParser(description="查询或生成 Pristima 已有专题报表")
    commands = main.add_subparsers(dest="command", required=True)
    for name, handler in (("list", list_reports), ("table", table_report), ("generate", pdf_report)):
        command = commands.add_parser(name)
        command.add_argument("--study-number", required=True)
        command.add_argument("--base-url", default=BASE_URL)
        command.add_argument("--timeout", type=float, default=300.0)
        if name != "list":
            command.add_argument("--report-name", required=True)
            command.add_argument("--rpt-data-type", required=True)
            command.add_argument("--rptformat-id", required=True)
            command.add_argument("--output", required=True)
            command.add_argument("--config-file")
            command.add_argument("--generated-by", help="报表生成人，未提供或为空时默认 xiaoxi")
        command.set_defaults(handler=handler)
    return main


def main() -> int:
    """运行命令并以 JSON 向 Agent 返回结果或错误。"""
    arguments = parser().parse_args()
    if arguments.timeout <= 0:
        print(json.dumps({"success": False, "error": "--timeout 必须大于 0"}, ensure_ascii=False), file=sys.stderr)
        return 2
    try:
        result = arguments.handler(arguments)
    except ClientError as error:
        print(json.dumps({"success": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"success": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
