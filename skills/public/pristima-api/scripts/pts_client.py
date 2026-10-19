"""Pristima XML API 客户端（PtsAPIServlet）。

支持两种会话模式：
1. 复用已有 JSESSIONID（推荐）：--jsessionid / --jsessionid-file / PTS_JSESSIONID /
   脚本内置 DEFAULT_JSESSIONID，或非空 --cookie-file，直接 POST 查询，不 GET、
   不登录、默认不 logout；
2. 新建会话：connect(GET 握手) → register/device-access → login →
   query/choices（任意多次）→ logout。

请求为 XML（PTS_RQ_*），响应默认原样输出 XML，可用 --json 转成通用 JSON 结构；
仅依赖 Python 标准库。凭据和长期 JSESSIONID 有内置默认值，可由同名环境变量或
命令行覆盖，绝不回显。
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import http.cookiejar
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ENV_BASE_URL = "PTS_API_BASE"      # 例：http://10.0.27.27/hubeipro_api/servlet/PtsAPIServlet
ENV_DEVICE_ID = "PTS_DEVICE_ID"
ENV_USER = "PTS_USER"
ENV_PASSWORD = "PTS_PASSWORD"
ENV_SITE_ID = "PTS_SITE_ID"
ENV_LANGUAGE = "PTS_LANGUAGE"
ENV_JSESSIONID = "PTS_JSESSIONID"  # 已有会话的 JSESSIONID（Postman cookie；敏感，勿回显）

# ---------------------------------------------------------------------------
# 现网连接信息（脚本内置默认值；同名环境变量存在时优先覆盖）。
# ⚠️ 凭据明文内置于此：本 skill 目录禁止外发、禁止推送公开仓库；换账号/换环境时
# 改这里或用环境变量覆盖；凭据一旦泄露，先到 Pristima 侧改密再更新此文件。
# ---------------------------------------------------------------------------
DEFAULT_BASE_URL = "http://10.0.27.27/hubeipro_api/servlet/PtsAPIServlet"
DEFAULT_SITE_ID = "21"             # Topgenxs 站点
DEFAULT_LANGUAGE = "0"             # 0 = 英语
DEFAULT_USER = "liumingli"         # 现网 API 用户（具 API data output 权限）
DEFAULT_PASSWORD = "qWe123456"

# 已有长期会话的 JSESSIONID（2026-10-19 实测可直接查询 ProtocolInfo）。这是 bearer
# 凭据：本目录禁止外发/开源；泄露后 logout/invalidate 该会话或重启 Pristima API，
# 并修改 Pristima 密码（只改密码不一定能杀死已有 API 会话）。优先级低于命令行参数、
# --jsessionid-file 和 PTS_JSESSIONID；显式给 --cookie-file 时不会使用此内置值。
DEFAULT_JSESSIONID = "w3BaB2bI1HvNqw87HSixZNSrti-DC8dI4m1VxSHW.ptspsaapi"

# 请求/响应 Doctype：现网实测（10.0.27.27 / zone=hubeipro_api）——
# study_data 的 Doctype 必须大写 PTS_RQ_STUDY_DATA（小写被拒 Invalid request string）；
# device_access / login / logout 两种大小写均可（现网实测）。
RQ_DEVICE_ACCESS = "pts_rq_device_access"
RQ_LOGIN = "pts_rq_login"
RQ_STUDY_DATA = "PTS_RQ_STUDY_DATA"
RQ_CHOICES = "pts_rq_choices"
RQ_EXTENDED_CHOICES = "pts_rq_extended_choices"
RQ_LOGOUT = "pts_rq_logout"

# 本技能只保留读取 API：以下写入/更新/插入类 Category 一律拒绝（大小写不敏感）
WRITE_CATEGORIES = {
    "studyeventupdate",
    "new labwise protocol",
    "new labwise colony",
    "rangeupdate",
    "intefacetransmissioninsert",
    "intefaceerrorinsert",
}

# 实测修正的 Category 拼写（2026-10-10 现网 81 分类全量验证）：
# 服务端 Category 名大小写敏感，以下文档原拼写会被拒 Key=214002 Not signed on，
# 生产正确拼写如下。查询时自动纠正，结果里带 category 标注实际使用的拼写。
CATEGORY_ALIASES = {
    "csection": "CSection",
    "prosubgroup": "ProSubGroup",
    "studyanimalphase": "AnimalPhase",
    "sampledrawlist": "SampleDrawlist",
}


def resolve_category(name: str) -> str:
    """把已知的文档错误拼写纠正为现网实测可用拼写。"""
    return CATEGORY_ALIASES.get(name.strip().lower(), name)


def reject_write_params(params: list[str]) -> None:
    """拒绝带写副作用的参数（SetPublished=Y 会改写事件表状态）。"""
    for item in params:
        if "=" not in item:
            continue
        name, value = item.split("=", 1)
        if name.strip().lower() == "setpublished" and value.strip().upper() in ("Y", "YES", "TRUE", "1"):
            raise ClientError("本技能只保留读取 API：SetPublished 会改写事件表状态，已拒绝")


class ClientError(Exception):
    """可向 Agent 展示的客户端或接口错误。"""


def env_or_none(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def build_xml(root_tag: str, params: list[str]) -> bytes:
    """按 --param 列表构造请求 XML；点号表示嵌套路径（如 Studies.StudyName）。"""
    root = ET.Element(root_tag)

    def sub_element(parent: ET.Element, path: str, value: str) -> None:
        parts = [p for p in path.split(".") if p]
        node = parent
        for name in parts[:-1]:
            # 同名中间节点复用，保证重复参数落进同一个包装（如多个 StudyName 共用一个 Studies）
            child = next((c for c in node if c.tag == name), None)
            if child is None:
                child = ET.SubElement(node, name)
            node = child
        child = ET.SubElement(node, parts[-1])
        child.text = value

    for item in params:
        if "=" not in item:
            raise ClientError(f"--param 必须是 Tag=Value 形式：{item!r}")
        name, value = item.split("=", 1)
        sub_element(root, name.strip(), value)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def send_xml(base_url: str, body: bytes, cookie_jar: http.cookiejar.CookieJar,
             timeout: float) -> tuple[int, str, bytes]:
    """POST XML 并携带会话 cookie；保留 HTTP 错误响应体。"""
    request = urllib.request.Request(
        base_url, data=body, method="POST",
        headers={"Content-Type": "text/xml; charset=utf-8"},
    )
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cookie_jar))
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Content-Type", ""), error.read()
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ClientError(f"无法连接 Pristima API：{error}") from error


def send_get(base_url: str, cookie_jar: http.cookiejar.CookieJar,
             timeout: float) -> tuple[int, str, bytes]:
    """GET 握手：建立会话并获得 cookie（响应应为 Connection_Accept）。"""
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cookie_jar))
    try:
        with opener.open(base_url, timeout=timeout) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Content-Type", ""), error.read()
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ClientError(f"无法连接 Pristima API：{error}") from error


def xml_to_json(xml_text: str):
    """把 XML 响应转成通用 JSON 结构：重复标签变列表，属性并入 '@attrs'。"""

    def convert(element: ET.Element):
        attrs = {"@" + k: v for k, v in element.attrib.items()}
        children: dict[str, list] = {}
        for child in element:
            children.setdefault(child.tag, []).append(convert(child))
        merged: dict = dict(attrs)
        for key, values in children.items():
            merged[key] = values if len(values) > 1 else values[0]
        text = (element.text or "").strip()
        if not merged:
            return text
        if text:
            merged["#text"] = text
        return merged

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as error:
        raise ClientError(f"接口未返回有效 XML：{error}") from error
    return {root.tag: convert(root)}


def load_cookie_jar(path: str | None) -> http.cookiejar.CookieJar:
    jar = http.cookiejar.MozillaCookieJar()
    if path:
        cookie_path = Path(path).expanduser()
        # filename 必须先设置：否则 save_cookie_jar 会静默跳过保存，
        # 会话 cookie 更新永远不落盘（生产实录"会话不稳定"的一部分原因）。
        jar.filename = str(cookie_path)
        if cookie_path.exists():
            try:
                jar.load(str(cookie_path), ignore_discard=True, ignore_expires=True)
            except (OSError, http.cookiejar.LoadError) as error:
                raise ClientError(f"无法读取 cookie 文件 {cookie_path}：{error}") from error
    return jar


def save_cookie_jar(jar: http.cookiejar.CookieJar, path: str | None) -> None:
    if path and jar.filename:
        try:
            jar.save(str(Path(path).expanduser()), ignore_discard=True, ignore_expires=True)
        except OSError as error:
            raise ClientError(f"无法保存 cookie 文件 {path}：{error}") from error


def cookie_path_for(base_url: str) -> str:
    """给 JSESSIONID 推导 cookie path：取 URL 的第一段（如 /hubeipro_api）。"""
    path = urllib.parse.urlsplit(base_url).path or "/"
    first = next((part for part in path.split("/") if part), "")
    return f"/{first}" if first else "/"


def set_jsessionid_cookie(jar: http.cookiejar.CookieJar, value: str,
                          base_url: str) -> None:
    """把 Postman/已有会话的 JSESSIONID 原样放进 cookie jar。

    注意：这里不做 `.ptstappserver` 后缀改写。用户从 Postman 拿到的值本身
    已经是服务端认可的完整值，改写反而可能把可用值弄坏。
    """
    value = (value or "").strip()
    # 允许直接粘贴 Postman 的 `JSESSIONID=...` 片段或整条 Cookie；只取 JSESSIONID。
    if value.lower().startswith("jsessionid="):
        value = value.split("=", 1)[1]
    value = value.split(";", 1)[0].strip().strip("\"'")
    if not value:
        raise ClientError("--jsessionid 不能为空")
    if any(ord(ch) < 32 for ch in value):
        raise ClientError("--jsessionid 含控制字符，拒绝使用")
    host = urllib.parse.urlsplit(base_url).hostname
    if not host:
        raise ClientError(f"无法从 --base-url 解析主机名：{base_url!r}")
    # 同一 host 下若已有旧 JSESSIONID，先清掉，避免 Cookie 头同时带两个值。
    clear_jsessionid(jar, host)
    cookie = http.cookiejar.Cookie(
        0, "JSESSIONID", value, None, False,
        host, False, False,
        cookie_path_for(base_url), True,
        False, None, True, None, None, {}, False,
    )
    jar.set_cookie(cookie)


def read_jsessionid_file(path: str) -> str:
    try:
        value = Path(path).expanduser().read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ClientError(f"无法读取 --jsessionid-file {path}：{error}") from error
    if not value:
        raise ClientError(f"--jsessionid-file 内容为空：{path}")
    return value


def jsessionid_of(args: argparse.Namespace) -> str | None:
    # 只有暴露 --jsessionid 的命令才读取该变量；connect/session 等建会话命令
    # 不应因为环境里恰好有 PTS_JSESSIONID/内置值就去复用/加锁。
    if not hasattr(args, "jsessionid"):
        return None
    inline = getattr(args, "jsessionid", None)
    path = getattr(args, "jsessionid_file", None)
    if inline and path:
        raise ClientError("--jsessionid 与 --jsessionid-file 只能二选一")
    if path:
        return read_jsessionid_file(path)
    if inline:
        return inline.strip()
    env_value = env_or_none(ENV_JSESSIONID)
    if env_value:
        return env_value
    # 显式 cookie 文件优先于内置默认值：这样 session 建出的新 jar 不会被
    # 内置长期会话覆盖，也让「用完显式 logout」的旧流程继续成立。
    if getattr(args, "cookie_file", None):
        return None
    return DEFAULT_JSESSIONID or None


def uses_jsessionid_source(args: argparse.Namespace) -> bool:
    """本次命令是否会按原值发送 JSESSIONID（用于关闭 .ptstappserver 改写）。

    显式 --cookie-file 且没有 --jsessionid/--jsessionid-file/PTS_JSESSIONID 时，
    表示调用方要使用 jar 里的会话，内置默认值不参与，后缀改写规则保持不变。
    """
    if not hasattr(args, "jsessionid"):
        return False
    if (getattr(args, "jsessionid", None)
            or getattr(args, "jsessionid_file", None)
            or env_or_none(ENV_JSESSIONID)):
        return True
    return bool(DEFAULT_JSESSIONID) and not getattr(args, "cookie_file", None)


def open_session_jar(args: argparse.Namespace) -> http.cookiejar.CookieJar:
    """加载 cookie 文件；若给了 --jsessionid(--file)，用原值覆盖 JSESSIONID。"""
    jar = load_cookie_jar(getattr(args, "cookie_file", None))
    jsessionid = jsessionid_of(args)
    if jsessionid:
        set_jsessionid_cookie(jar, jsessionid, base_url_of(args))
    return jar


def session_lock_path(args: argparse.Namespace) -> str | None:
    """同一会话的串行锁路径。

    cookie 文件优先用 `<cookie-file>.lock`；只给 --jsessionid 时用其哈希做锁名，
    避免把会话值写进文件名。跨容器不共享，跨容器并发仍需外部代理/队列。
    """
    cookie_file = getattr(args, "cookie_file", None)
    if cookie_file:
        return str(Path(cookie_file).expanduser().resolve()) + ".lock"
    jsessionid = jsessionid_of(args)
    if jsessionid:
        digest = hashlib.sha256(jsessionid.encode("utf-8")).hexdigest()[:16]
        return str(Path(tempfile.gettempdir()) / f"pristima_jsession_{digest}.lock")
    return None


@contextlib.contextmanager
def session_lock(path: str | None, timeout: float):
    """跨进程串行化同一会话；服务端一个 JSESSIONID 只有一个可变 handler。"""
    if not path:
        yield
        return
    lock_path = Path(path)
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as error:
        raise ClientError(f"无法创建会话锁 {lock_path}：{error}") from error
    acquired = False
    deadline = time.monotonic() + max(float(timeout), 0.0)
    try:
        if os.name == "nt":
            import msvcrt
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"0")
            while True:
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    acquired = True
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise ClientError(
                            f"等待会话锁超时（{lock_path}）：另一个任务正在使用同一会话。"
                            "请串行调用，或增大 --lock-timeout。")
                    time.sleep(0.2)
        else:
            import fcntl
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise ClientError(
                            f"等待会话锁超时（{lock_path}）：另一个任务正在使用同一会话。"
                            "请串行调用，或增大 --lock-timeout。")
                    time.sleep(0.2)
        yield
    finally:
        if acquired:
            try:
                if os.name == "nt":
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(fd)


def clear_jsessionid(jar: http.cookiejar.CookieJar, domain: str | None = None) -> None:
    """清掉本地 JSESSIONID（退出成功后，或换用新的 --jsessionid 时）。

    domain 为空清全部；指定 domain 时只清该主机的 cookie，避免误删同一 jar
    里其他系统的 JSESSIONID。
    """
    for cookie in list(jar):
        if cookie.name.lower() != "jsessionid":
            continue
        if domain and cookie.domain.lstrip(".").lower() != domain.lstrip(".").lower():
            continue
        jar.clear(cookie.domain, cookie.path, cookie.name)


def has_jsessionid(jar: http.cookiejar.CookieJar, base_url: str | None = None) -> bool:
    """cookie 文件里是否真的有一个可复用的 JSESSIONID（其他 cookie 不算会话）。"""
    host = urllib.parse.urlsplit(base_url).hostname if base_url else None
    for cookie in jar:
        if cookie.name.lower() != "jsessionid":
            continue
        if host and cookie.domain.lstrip(".").lower() != host.lower():
            continue
        return True
    return False


def transform_jsessionid(jar: http.cookiejar.CookieJar, suffix: str | None) -> None:
    """现网实测：服务器只认 `JSESSIONID=<首段>.<后缀>`（后缀如 ptstappserver）。

    Set-Cookie 里的 JSESSIONID 值需截到第一个点再拼上服务器后缀；直接回送完整值
    不保证可用。suffix 为空则不改写。
    """
    if not suffix:
        return
    for cookie in list(jar):
        if cookie.name.lower() != "jsessionid":
            continue
        first_part = cookie.value.split(".")[0]
        new_value = f"{first_part}.{suffix}"
        if new_value == cookie.value:
            continue
        rewritten = http.cookiejar.Cookie(
            cookie.version, cookie.name, new_value, cookie.port, cookie.port_specified,
            cookie.domain, cookie.domain_specified, cookie.domain_initial_dot,
            cookie.path, cookie.path_specified, cookie.secure, cookie.expires,
            cookie.discard, cookie.comment, cookie.comment_url,
            dict(getattr(cookie, "_rest", {})), cookie.rfc2109)
        jar.set_cookie(rewritten)


def parse_xml_response(status: int, body: bytes) -> str:
    """返回可读的响应文本；非 2xx 或 pts_rs_failure 失败信封时抛 ClientError。"""
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        text = body.decode("latin-1", errors="replace")
    if not 200 <= status < 300:
        raise ClientError(f"Pristima API 返回 HTTP {status}：{text.strip()[:500]}")
    if not text.strip():
        raise ClientError("Pristima API 返回空响应")
    if re.search(r"<Doctype>\s*pts_rs_failure\s*</Doctype>", text, re.IGNORECASE):
        key = re.search(r"<Key>(.*?)</Key>", text, re.S)
        message = re.search(r"<FailureMessage>(.*?)</FailureMessage>", text, re.S)
        detail = f"（Key={key.group(1).strip()}）" if key else ""
        extra = f"：{message.group(1).strip()}" if message else ""
        hint = ""
        if "214002" in text or "not signed on" in text.lower():
            hint = ("（214002 Not signed on 不是会话问题：先核对 Category 名大小写——实测"
                    "大小写敏感（如 CSection 可用、文档拼写 Csection 被拒）；若拼写无误则是"
                    "账号对该分类数据无授权。不要为此重建会话；反复登录会累积占用"
                    "max_user_connection=20 的会话名额）")
        raise ClientError(f"Pristima API 返回失败{detail}{extra}{hint}")
    return text


def credentials(args: argparse.Namespace) -> tuple[str, str]:
    user = args.user or env_or_none(ENV_USER) or DEFAULT_USER
    password = args.password or env_or_none(ENV_PASSWORD) or DEFAULT_PASSWORD
    return user, password


def add_session_flags(command: argparse.ArgumentParser, register: bool = False,
                      allow_jsessionid: bool = False) -> None:
    command.add_argument("--base-url", default=env_or_none(ENV_BASE_URL) or DEFAULT_BASE_URL,
                         help=f"缺省取环境变量 {ENV_BASE_URL}，再缺省用脚本内置的现网地址")
    command.add_argument("--timeout", type=float, default=60.0)
    command.add_argument("--cookie-file",
                         help="会话 cookie 文件，跨命令复用同一会话；显式提供时会屏蔽内置默认 JSESSIONID")
    command.add_argument("--cookie-suffix", default="ptstappserver",
                         help="非 --jsessionid 模式下 JSESSIONID 的改写后缀（现网实测需要），"
                              "传空字符串关闭改写；--jsessionid 模式原值发送、不改写")
    command.add_argument("--lock-timeout", type=float, default=300.0,
                         help="同一 cookie/JSESSIONID 的跨进程串行锁等待秒数（默认 300）")
    if allow_jsessionid:
        group = command.add_mutually_exclusive_group()
        group.add_argument("--jsessionid", default=None,
                           help=f"直接复用已有 JSESSIONID（Postman cookie 值），跳过登录；"
                                f"缺省依次取环境变量 {ENV_JSESSIONID}、脚本内置长期会话。"
                                "原值发送，不改写后缀；敏感信息，勿在日志/输出中回显")
        group.add_argument("--jsessionid-file",
                           help="从文件读取 JSESSIONID（优先于环境变量，避免命令行/进程列表泄露）")
    if register:
        command.add_argument("--device-id", default=env_or_none(ENV_DEVICE_ID),
                             help="已注册设备的 DeviceID（首次注册时可省略）")
        command.add_argument("--user", default=env_or_none(ENV_USER) or DEFAULT_USER,
                             help="缺省取环境变量，再缺省用脚本内置的现网账号")
        command.add_argument("--password", default=env_or_none(ENV_PASSWORD) or DEFAULT_PASSWORD,
                             help="缺省取环境变量，再缺省用脚本内置的现网凭据")
        command.add_argument("--language", default=env_or_none(ENV_LANGUAGE) or DEFAULT_LANGUAGE,
                             help=f"缺省取环境变量 {ENV_LANGUAGE}，再缺省 {DEFAULT_LANGUAGE}（英语）")
        command.add_argument("--site-id", default=env_or_none(ENV_SITE_ID) or DEFAULT_SITE_ID,
                             help=f"缺省取环境变量 {ENV_SITE_ID}，再缺省 {DEFAULT_SITE_ID}（Topgenxs）")
    command.add_argument("--json", action="store_true", help="响应转 JSON 输出")


def main() -> int:
    main_parser = argparse.ArgumentParser(description="Pristima XML API 客户端（PtsAPIServlet）")
    commands = main_parser.add_subparsers(dest="command", required=True)

    connect = commands.add_parser("connect", help="GET 握手，建立会话并获得 cookie")
    add_session_flags(connect)
    connect.set_defaults(handler=handle_connect)

    register = commands.add_parser("register", help="首次连接：注册设备并取得 DeviceID")
    add_session_flags(register, register=True)
    register.add_argument("--device-name", default="DeerFlow Client")
    register.add_argument("--device-location", default="DeerFlow")
    register.set_defaults(handler=handle_register)

    device = commands.add_parser("device-access", help="用已有 DeviceID 申请设备访问")
    add_session_flags(device, register=True)
    device.set_defaults(handler=handle_device_access)

    login = commands.add_parser("login", help="用 API 账号登录（UserID/Password）")
    add_session_flags(login)
    login.add_argument("--user", default=env_or_none(ENV_USER) or DEFAULT_USER,
                       help="缺省取环境变量，再缺省用脚本内置的现网账号")
    login.add_argument("--password", default=env_or_none(ENV_PASSWORD) or DEFAULT_PASSWORD,
                       help="缺省取环境变量，再缺省用脚本内置的现网凭据")
    login.add_argument("--language", default=env_or_none(ENV_LANGUAGE) or DEFAULT_LANGUAGE,
                       help=f"缺省取环境变量 {ENV_LANGUAGE}，再缺省 {DEFAULT_LANGUAGE}（英语）")
    login.set_defaults(handler=handle_login)

    query = commands.add_parser("query", help="查询数据（PTS_RQ_STUDY_DATA），默认先探测条数、超阈值自动分段；新建会话默认退出，复用会话默认保留")
    add_session_flags(query, register=True, allow_jsessionid=True)
    query.add_argument("--category", required=True, help="API 分类名，如 BodyWeight、ProtocolInfo")
    query.add_argument("--param", action="append", default=[],
                       help="Tag=Value，可重复；点号嵌套，如 Studies.StudyName=08-0810")
    query.add_argument("--output", help="把原始 XML 响应保存到该路径（不覆盖已有文件）；分段时保存为 .partNNN.xml")
    query.add_argument("--max-records", type=int, default=10000,
                       help="单次返回超过该条数时按时间窗自动分段（默认 10000）")
    query.add_argument("--no-probe", action="store_true",
                       help="跳过 CountOnly 探测，直接单次查询")
    query.add_argument("--with-session", action="store_true",
                       help="cookie 里没有可用会话时先按标准顺序建会话（含就绪等待）")
    query.add_argument("--keep-session", action="store_true",
                       help="新建会话也保留、不退出账号（复用已有会话默认就保留）")
    query.add_argument("--no-login", action="store_true",
                       help="cookie/JSESSIONID 失效时不要自动登录，直接报错")
    query.add_argument("--device-name", default="DeerFlow Client")
    query.add_argument("--device-location", default="DeerFlow")
    query.add_argument("--login-wait", type=float, default=3.0,
                       help="--with-session 建会话后的就绪等待秒数（现网实测约需 3 秒）")
    query.set_defaults(handler=handle_query)

    choices = commands.add_parser("choices", help="查询选择项（站点/语言等，pts_rq_choices）")
    add_session_flags(choices, allow_jsessionid=True)
    choices.add_argument("--module", default="Security")
    choices.add_argument("--category", default="Display")
    choices.add_argument("--location", default="Login")
    choices.add_argument("--name", default="Sites")
    choices.add_argument("--extended", action="store_true", help="使用 pts_rq_extended_choices")
    choices.add_argument("--output", help="把原始 XML 响应保存到该路径（不覆盖已有文件）")
    choices.set_defaults(handler=handle_choices)

    send = commands.add_parser("send", help="发送任意准备好的 XML 请求文件")
    add_session_flags(send, allow_jsessionid=True)
    send.add_argument("--xml-file", required=True, help="请求 XML 文件路径（UTF-8）")
    send.add_argument("--output", help="把原始 XML 响应保存到该路径（不覆盖已有文件）")
    send.set_defaults(handler=handle_send)

    logout = commands.add_parser("logout", help="登出并结束会话")
    add_session_flags(logout, allow_jsessionid=True)
    logout.add_argument("--access-status", default="0")
    logout.add_argument("--force", action="store_true",
                        help="未显式指定会话时，允许退出脚本内置的长期 JSESSIONID")
    logout.set_defaults(handler=handle_logout)

    env_check = commands.add_parser("env-check", help="检查连接环境变量是否注入到位（只报名字，不报值）")
    env_check.set_defaults(handler=handle_env_check)

    session_cmd = commands.add_parser("session",
                                      help="按标准顺序建立会话：握手→设备登录→账号登录（含就绪等待）")
    add_session_flags(session_cmd, register=True)
    session_cmd.add_argument("--device-name", default="DeerFlow Client")
    session_cmd.add_argument("--device-location", default="DeerFlow")
    session_cmd.add_argument("--login-wait", type=float, default=3.0,
                             help="账号登录后等待会话就绪的秒数（现网实测约需 3 秒，测试可传 0）")
    session_cmd.add_argument("--force", action="store_true",
                             help="cookie 文件里已有 JSESSIONID 时仍强制重建（会覆盖原会话）")
    session_cmd.set_defaults(handler=handle_session)

    batch_cmd = commands.add_parser("batch",
                                    help="单进程批量查询：复用会话或建会话→顺序查询；复用会话默认保留，新建会话默认退出")
    add_session_flags(batch_cmd, register=True, allow_jsessionid=True)
    batch_cmd.add_argument("--spec", required=True,
                           help="批处理 spec JSON：{\"queries\": [{\"category\": ..., \"params\": {...}, \"output\": ...}]}")
    batch_cmd.add_argument("--device-name", default="DeerFlow Client")
    batch_cmd.add_argument("--device-location", default="DeerFlow")
    batch_cmd.add_argument("--login-wait", type=float, default=3.0,
                           help="账号登录后等待会话就绪的秒数（现网实测约需 3 秒，测试可传 0）")
    batch_cmd.add_argument("--no-logout", action="store_true",
                           help="结束时保留会话不退出账号（复用会话默认就保留）")
    batch_cmd.add_argument("--no-login", action="store_true",
                           help="cookie/JSESSIONID 失效时不要自动重建会话，直接报错")
    batch_cmd.add_argument("--resume", action="store_true",
                           help="跳过 output 文件已存在且非空的查询项（断点续跑，不覆盖已拿到的数据）")
    batch_cmd.set_defaults(handler=handle_batch)

    args = main_parser.parse_args()
    if getattr(args, "timeout", 60) <= 0:
        print(json.dumps({"success": False, "error": "--timeout 必须大于 0"},
                         ensure_ascii=False), file=sys.stderr)
        return 2
    if getattr(args, "lock_timeout", 300) < 0:
        print(json.dumps({"success": False, "error": "--lock-timeout 不能为负数"},
                         ensure_ascii=False), file=sys.stderr)
        return 2
    # --jsessionid / 内置 JSESSIONID 的原值必须原样发送：关闭 .ptstappserver 改写，
    # 避免把 Postman 里已经可用的值截断/重拼。
    if uses_jsessionid_source(args):
        args.cookie_suffix = None
    try:
        lock_path = session_lock_path(args)
        with session_lock(lock_path, getattr(args, "lock_timeout", 300.0)):
            result = args.handler(args)
    except ClientError as error:
        print(json.dumps({"success": False, "error": str(error)},
                         ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"success": True, **result}, ensure_ascii=False, indent=2))
    return 0


def base_url_of(args: argparse.Namespace) -> str:
    if not args.base_url:
        raise ClientError(
            f"缺少 API 地址：请用 --base-url 或环境变量 {ENV_BASE_URL} 提供，"
            "格式为 http://<API服务器>/<zone名>/servlet/PtsAPIServlet（zone 名见服务器 API.INI）")
    return args.base_url


def save_response(text: str, output: str | None, overwrite: bool = False) -> None:
    if not output:
        return
    target = Path(output).expanduser().resolve()
    if target.exists() and not overwrite:
        raise ClientError(f"输出文件已存在：{target}")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    except OSError as error:
        raise ClientError(f"无法保存 {target}：{error}") from error


def present(args: argparse.Namespace, text: str) -> dict:
    save_response(text, getattr(args, "output", None))
    if args.json:
        return {"response": xml_to_json(text)}
    return {"response": text}


# ---------------- 大结果集分段（先探测条数，超阈值按时间窗二分） ----------------

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_MONTH_MAP = {m.upper(): i + 1 for i, m in enumerate(_MONTHS)}
_PTS_DT_RE = re.compile(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})(?:\.\d+)?")
_COUNT_RE = re.compile(r"<Count\s*>\s*(\d+)\s*</Count\s*>", re.I)


def parse_pts_datetime(value: str) -> dt.datetime:
    """解析 dd-mmm-yyyy hh:mm:ss（英文月份缩写，兼容大小写与小数秒）。"""
    match = _PTS_DT_RE.search(value)
    if not match:
        raise ClientError(f"无法解析 Pristima 日期时间：{value!r}（应为 dd-mmm-yyyy hh:mm:ss）")
    day, mon, year, hh, mm, ss = match.groups()
    month = _MONTH_MAP.get(mon.upper())
    if month is None:
        raise ClientError(f"无法识别月份缩写：{mon}")
    return dt.datetime(int(year), month, int(day), int(hh), int(mm), int(ss))


def format_pts_datetime(value: dt.datetime) -> str:
    return (f"{value.day:02d}-{_MONTHS[value.month - 1]}-{value.year} "
            f"{value.hour:02d}:{value.minute:02d}:{value.second:02d}")


def parse_counts(xml_text: str) -> list[int]:
    """提取响应里的全部 <Count> 值（按专题/测量名分组时会有多个）。"""
    return [int(m) for m in _COUNT_RE.findall(xml_text)]


def find_param(params: list[str], tag_lower: str):
    """按 Tag 名（大小写不敏感）找参数；返回 (原参数串, 值)，找不到返回 (None, None)。"""
    for item in params:
        if "=" not in item:
            continue
        name, value = item.split("=", 1)
        if name.strip().lower() == tag_lower:
            return item, value
    return None, None


def strip_params(params: list[str], tags_lower: set[str]) -> list[str]:
    """去掉指定 Tag（大小写不敏感）的参数。"""
    return [p for p in params
            if not ("=" in p and p.split("=", 1)[0].strip().lower() in tags_lower)]


def merge_json(base, extra):
    """合并两个分段转换出的 JSON：列表拼接、字典递归、标量冲突后者覆盖。"""
    if base is None:
        return extra
    if isinstance(base, dict) and isinstance(extra, dict):
        merged = dict(base)
        for key, value in extra.items():
            merged[key] = merge_json(merged.get(key), value)
        return merged
    if isinstance(base, list):
        return base + (extra if isinstance(extra, list) else [extra])
    if isinstance(extra, list):
        return [base] + extra
    return extra if base != extra else base


def probe_count(args: argparse.Namespace, jar: http.cookiejar.CookieJar,
                params: list[str]) -> int | None:
    """发送 CountOnly=Y 探测并返回总条数；不支持或失败时返回 None。"""
    probe = [f"Doctype={RQ_STUDY_DATA}", f"Category={args.category}", *params, "CountOnly=Y"]
    status, _, body = send_xml(base_url_of(args), build_xml("PTS", probe), jar, args.timeout)
    try:
        text = parse_xml_response(status, body)
    except ClientError:
        return None
    counts = parse_counts(text)
    return sum(counts) if counts else None


def resolve_window(args: argparse.Namespace, jar: http.cookiejar.CookieJar,
                   total: int) -> tuple[dt.datetime, dt.datetime]:
    """确定分段的时间范围：优先用请求里的 Start/EndDateTime，否则借 DataDateRange。"""
    start = end = None
    _, value = find_param(args.param, "startdatetime")
    if value:
        start = parse_pts_datetime(value.strip())
    _, value = find_param(args.param, "enddatetime")
    if value:
        end = parse_pts_datetime(value.strip())
    if start and end:
        return start, end
    _, mt = find_param(args.param, "measurementtype")
    if not mt:
        raise ClientError(
            f"共 {total} 条超过 --max-records（{args.max_records}），但请求里没有日期范围"
            "也没有 MeasurementType，无法自动分段。请提供 StartDateTime/EndDateTime"
            "（或 MeasurementType 以借用 DataDateRange 的日期范围），或缩小筛选条件，"
            "或调高 --max-records。")
    dr_params = [f"Doctype={RQ_STUDY_DATA}", "Category=DataDateRange"]
    for tag in ("studyname", "types", "generation", "measurementtype"):
        item, _ = find_param(args.param, tag)
        if item:
            dr_params.append(item)
    status, _, body = send_xml(base_url_of(args), build_xml("PTS", dr_params), jar, args.timeout)
    text = parse_xml_response(status, body)
    start_m = re.search(r"<StartDateTime>(.*?)</StartDateTime>", text, re.I)
    end_m = re.search(r"<EndDateTime>(.*?)</EndDateTime>", text, re.I)
    if not start_m or not end_m:
        raise ClientError(
            f"共 {total} 条超过 --max-records（{args.max_records}），但 DataDateRange "
            "未返回日期范围。请显式提供 StartDateTime/EndDateTime，或调高 --max-records。")
    return parse_pts_datetime(start_m.group(1)), parse_pts_datetime(end_m.group(1))


def plan_segments(start_dt: dt.datetime, end_dt: dt.datetime, max_records: int,
                  prober) -> list[tuple[dt.datetime, dt.datetime, int | None]]:
    """二分时间窗：条数≤阈值的窗口直接取数，超过的继续对半，直到按天仍超限才原样取。"""
    segments: list[tuple[dt.datetime, dt.datetime, int | None]] = []

    def walk(lo: dt.datetime, hi: dt.datetime) -> None:
        if len(segments) >= 200:
            raise ClientError("分段数超过 200，请缩小时间范围或调高 --max-records")
        count = prober(lo, hi)
        if count == 0:
            return
        if count is None or count <= max_records or (hi - lo) <= dt.timedelta(days=1):
            segments.append((lo, hi, count))
            return
        mid = lo + (hi - lo) / 2
        walk(lo, mid)
        walk(mid, hi)

    walk(start_dt, end_dt)
    return segments


def paginated_query(args: argparse.Namespace, jar: http.cookiejar.CookieJar) -> dict:
    """先探测条数，超过 --max-records 时按时间窗分段抓取。"""
    total = probe_count(args, jar, args.param)
    if total is None:
        result = single_query(args, jar)
        result["note"] = "该 Category 不支持 CountOnly 探测，已按单次查询返回"
        return result
    if total <= args.max_records:
        result = single_query(args, jar)
        result["note"] = f"CountOnly 探测 {total} 条，未超 --max-records（{args.max_records}），单次返回"
        return result

    start_dt, end_dt = resolve_window(args, jar, total)
    base = [f"Doctype={RQ_STUDY_DATA}", f"Category={args.category}"]
    user_params = strip_params(args.param, {"startdatetime", "enddatetime"})

    def prober(lo: dt.datetime, hi: dt.datetime) -> int | None:
        return probe_count(args, jar, [*user_params,
                                       f"StartDateTime={format_pts_datetime(lo)}",
                                       f"EndDateTime={format_pts_datetime(hi)}"])

    segments = plan_segments(start_dt, end_dt, args.max_records, prober)
    texts: list[str] = []
    per_counts: list[int | None] = []
    for lo, hi, expected in segments:
        params = [*base, *user_params,
                  f"StartDateTime={format_pts_datetime(lo)}",
                  f"EndDateTime={format_pts_datetime(hi)}"]
        status, _, body = send_xml(base_url_of(args), build_xml("PTS", params), jar, args.timeout)
        text = parse_xml_response(status, body)
        texts.append(text)
        counts = parse_counts(text)
        per_counts.append(sum(counts) if counts else expected)

    result: dict = {
        "category": args.category,
        "pagination": {
            "total": total,
            "range": [format_pts_datetime(start_dt), format_pts_datetime(end_dt)],
            "segments": len(texts),
            "per_segment_counts": per_counts,
        },
    }
    if args.json:
        merged: dict = {}
        for text in texts:
            converted = xml_to_json(text)
            for key, value in converted.items():
                merged[key] = merge_json(merged.get(key), value)
        if args.output:
            save_response(json.dumps(merged, ensure_ascii=False, indent=2), args.output)
            result["files"] = [args.output]
        else:
            result["response"] = merged
        return result
    if not args.output:
        raise ClientError("分段处理需要 --output（各分段保存为 .partNNN.xml）或 --json")
    files = []
    for i, text in enumerate(texts, 1):
        target = Path(args.output).expanduser().resolve()
        part = target.parent / f"{target.stem}.part{i:03d}{target.suffix}"
        save_response(text, str(part))
        files.append(str(part))
    result["files"] = files
    return result


def handle_connect(args: argparse.Namespace) -> dict:
    jar = load_cookie_jar(args.cookie_file)
    status, _, body = send_get(base_url_of(args), jar, args.timeout)
    text = parse_xml_response(status, body)
    transform_jsessionid(jar, getattr(args, "cookie_suffix", None))
    save_cookie_jar(jar, args.cookie_file)
    return {"http": status, "cookies": len(jar), "response": text}


def handle_register(args: argparse.Namespace) -> dict:
    jar = load_cookie_jar(args.cookie_file)
    user, password = credentials(args)
    params = [
        f"Doctype={RQ_DEVICE_ACCESS}",
        f"DeviceName={args.device_name}", f"DeviceLocation={args.device_location}",
        "InitialDeviceName=True", f"Language={args.language}",
        f"SiteID={args.site_id}",
    ]
    if user:
        params += [f"UserID={user}", f"Password={password}"]
    status, _, body = send_xml(base_url_of(args), build_xml("PTS", params), jar, args.timeout)
    text = parse_xml_response(status, body)
    transform_jsessionid(jar, getattr(args, "cookie_suffix", None))
    save_cookie_jar(jar, args.cookie_file)
    return {"response": text}


def handle_device_access(args: argparse.Namespace) -> dict:
    if not args.device_id:
        raise ClientError(f"缺少 DeviceID：请用 --device-id 或环境变量 {ENV_DEVICE_ID}")
    jar = load_cookie_jar(args.cookie_file)
    status, _, body = send_xml(base_url_of(args),
                               build_xml("PTS", [f"Doctype={RQ_DEVICE_ACCESS}",
                                                 f"DeviceID={args.device_id}"]),
                               jar, args.timeout)
    text = parse_xml_response(status, body)
    transform_jsessionid(jar, getattr(args, "cookie_suffix", None))
    save_cookie_jar(jar, args.cookie_file)
    return {"response": text}


def handle_login(args: argparse.Namespace) -> dict:
    user, password = credentials(args)
    jar = load_cookie_jar(args.cookie_file)
    params = [f"Doctype={RQ_LOGIN}", f"UserID={user}", f"Password={password}",
              f"Language={args.language}"]
    status, _, body = send_xml(base_url_of(args), build_xml("PTS", params), jar, args.timeout)
    text = parse_xml_response(status, body)
    transform_jsessionid(jar, getattr(args, "cookie_suffix", None))
    save_cookie_jar(jar, args.cookie_file)
    return {"response": text}


def single_query(args: argparse.Namespace, jar: http.cookiejar.CookieJar) -> dict:
    """单次查询（原始行为）。"""
    params = [f"Doctype={RQ_STUDY_DATA}", f"Category={args.category}", *args.param]
    status, _, body = send_xml(base_url_of(args),
                               build_xml("PTS", params), jar, args.timeout)
    text = parse_xml_response(status, body)
    return present(args, text)


def handle_query(args: argparse.Namespace) -> dict:
    if args.category.strip().lower() in WRITE_CATEGORIES:
        raise ClientError(f"本技能只保留读取 API：Category {args.category!r} 是写入/更新/插入类操作，已拒绝")
    reject_write_params(args.param)
    if args.max_records <= 0:
        raise ClientError("--max-records 必须大于 0")
    requested = args.category
    args.category = resolve_category(requested)
    jar = open_session_jar(args)
    reused_session = has_jsessionid(jar, base_url_of(args))
    session_created = False
    if args.with_session and not reused_session:
        if getattr(args, "no_login", False):
            raise ClientError(
                "没有可用会话，且指定了 --no-login：--with-session 需要登录，二者冲突。"
                "请提供 --jsessionid/--jsessionid-file 或非空 --cookie-file。")
        establish_session(args, jar, args.login_wait)
        session_created = True
    rebuilt = False
    result = None
    logout_note = None

    def run_query() -> dict:
        if args.no_probe or find_param(args.param, "countonly")[0]:
            return single_query(args, jar)
        return paginated_query(args, jar)

    try:
        try:
            result = run_query()
        except ClientError as error:
            if not is_session_error(error):
                raise
            if not reused_session:
                if args.with_session:
                    raise ClientError(
                        "新建会话后查询仍返回 401 Session not found：会话可能尚未就绪。"
                        "请增大 --login-wait 后重试（重复登录也会占用 20 个会话名额）。") from error
                raise ClientError(
                    "没有可用会话：请求返回 401 Session not found。"
                    "请用 --jsessionid/--jsessionid-file 提供已有 cookie，"
                    "或加 --with-session 新建会话。") from error
            if getattr(args, "no_login", False):
                raise ClientError(
                    f"复用会话已失效，且指定了 --no-login：{error}") from error
            # cookie/JSESSIONID 过期：只在 401 时重建一次，成功后重试原查询。
            establish_session(args, jar, args.login_wait)
            rebuilt = True
            session_created = True
            result = run_query()
    finally:
        # 复用会话默认保留（否则每次查询都 logout 等于把可复用 cookie 杀掉）；
        # 本次新建（含 401 后重建）的会话默认退出。放在 finally 里，查询报错时
        # 也不会留下孤儿会话。
        session_reused = reused_session and not rebuilt
        if session_created and not args.keep_session:
            try:
                status, _, body = send_xml(
                    base_url_of(args),
                    build_xml("PTS", [f"Doctype={RQ_LOGOUT}", "AccessStatus=0"]),
                    jar, args.timeout)
                parse_xml_response(status, body)
                clear_jsessionid(jar, urllib.parse.urlsplit(base_url_of(args)).hostname)
                logout_note = "已退出本次新建/重建的会话"
            except ClientError as error:
                logout_note = f"退出账号失败（可忽略）：{str(error)[:150]}"
        elif session_reused:
            logout_note = "已保留复用/指定的会话（未退出账号）"
        elif session_created:
            logout_note = "已保留本次新建/重建的会话（--keep-session）"
        # 没有会话也没有新建（例如未加 --with-session 直接查）：不发 logout。
        transform_jsessionid(jar, getattr(args, "cookie_suffix", None))
        save_cookie_jar(jar, args.cookie_file)
    result["category"] = args.category
    if args.category != requested:
        result["category_requested"] = requested
        result["note"] = f"Category 拼写已按现网实测纠正：{requested} → {args.category}"
    result["session_reused"] = reused_session and not rebuilt
    if rebuilt:
        result["session_rebuilt"] = True
    result["logout"] = logout_note
    return result


def handle_choices(args: argparse.Namespace) -> dict:
    jar = open_session_jar(args)
    doctype = RQ_EXTENDED_CHOICES if args.extended else RQ_CHOICES
    params = [f"Doctype={doctype}", f"Module={args.module}", f"Category={args.category}",
              f"Location={args.location}", f"Name={args.name}"]
    status, _, body = send_xml(base_url_of(args), build_xml("PTS", params), jar, args.timeout)
    text = parse_xml_response(status, body)
    transform_jsessionid(jar, getattr(args, "cookie_suffix", None))
    save_cookie_jar(jar, args.cookie_file)
    return present(args, text)


def handle_send(args: argparse.Namespace) -> dict:
    xml_path = Path(args.xml_file).expanduser().resolve()
    try:
        payload = xml_path.read_bytes()
    except OSError as error:
        raise ClientError(f"无法读取 {xml_path}：{error}") from error
    try:
        root = ET.fromstring(payload.decode("utf-8", errors="replace"))
    except ET.ParseError as error:
        raise ClientError(f"请求 XML 无法解析：{error}") from error
    categories = [e.text or "" for e in root.iter() if e.tag == "Category"]
    if any(c.strip().lower() in WRITE_CATEGORIES for c in categories):
        raise ClientError("本技能只保留读取 API：请求中的 Category 属于写入/更新/插入类操作，已拒绝")
    jar = open_session_jar(args)
    status, _, body = send_xml(base_url_of(args), payload, jar, args.timeout)
    text = parse_xml_response(status, body)
    transform_jsessionid(jar, getattr(args, "cookie_suffix", None))
    save_cookie_jar(jar, args.cookie_file)
    return present(args, text)


def handle_env_check(args: argparse.Namespace) -> dict:
    """报告连接信息的来源（env=环境变量覆盖 / builtin=脚本内置默认），绝不回显密码值。"""
    sources = {}
    for name in (ENV_BASE_URL, ENV_USER, ENV_PASSWORD,
                 ENV_SITE_ID, ENV_LANGUAGE, ENV_DEVICE_ID, ENV_JSESSIONID):
        if env_or_none(name):
            sources[name] = "env"
        elif name == ENV_JSESSIONID and not DEFAULT_JSESSIONID:
            sources[name] = "unset"
        else:
            sources[name] = "builtin"
    return {
        "sources": sources,
        "effective_site_id": env_or_none(ENV_SITE_ID) or DEFAULT_SITE_ID,
        "effective_language": env_or_none(ENV_LANGUAGE) or DEFAULT_LANGUAGE,
        "note": "builtin=脚本内置的现网连接信息/长期会话（凭据与 JSESSIONID 明文内置于脚本，"
                "本目录禁止外发）；env=同名环境变量覆盖；unset=未提供。",
        "ok": True,
    }


def login_limit_message() -> str:
    return (
        "账号登录返回 210064：该账号已达到服务端 max_user_connection=20 的未退出会话上限，"
        "不是 ScreenLock，也不是 10 分钟锁屏。本部署的会话不会自动过期"
        "（web.xml session-timeout=-1，API.ini 没有 SessionTermination）。"
        "处置：优先复用现有 JSESSIONID（--jsessionid/--jsessionid-file 或 --cookie-file），"
        "停止重复登录；要释放名额只能 logout 旧会话或重启 API 应用。"
    )


def establish_session(args: argparse.Namespace, jar: http.cookiejar.CookieJar,
                      wait: float) -> None:
    """标准会话顺序（现网实测，用户确认）：GET 握手 → 设备登录（register）→ 账号登录。

    登录后等服务端会话就绪（实测约需 3 秒，过早查询会失败）；210064 会话上限
    给出可执行提示（不是 ScreenLock，也不是 10 分钟锁屏）。
    """
    url = base_url_of(args)
    # 1) GET 握手
    status, _, body = send_get(url, jar, args.timeout)
    text = parse_xml_response(status, body)
    if "connection" not in text.lower():
        raise ClientError(f"GET 握手异常（期望 Connection accepted）：{text.strip()[:200]}")
    # 2) 设备登录（现网唯一可用方式：InitialDeviceName=True + 固定设备名；不要用
    #    device-access——现网没有可用的 DeviceID）
    user, password = credentials(args)
    params = [f"Doctype={RQ_DEVICE_ACCESS}",
              f"DeviceName={args.device_name}", f"DeviceLocation={args.device_location}",
              "InitialDeviceName=True", f"Language={args.language}",
              f"SiteID={args.site_id}", f"UserID={user}", f"Password={password}"]
    status, _, body = send_xml(url, build_xml("PTS", params), jar, args.timeout)
    text = parse_xml_response(status, body)
    if "pts_rs_device_access" not in text.lower():
        raise ClientError(f"设备登录失败：{text.strip()[:300]}")
    # 3) 账号登录
    params = [f"Doctype={RQ_LOGIN}", f"UserID={user}", f"Password={password}",
              f"Language={args.language}"]
    status, _, body = send_xml(url, build_xml("PTS", params), jar, args.timeout)
    try:
        text = parse_xml_response(status, body)
    except ClientError as error:
        if "210064" in str(error):
            raise ClientError(login_limit_message()) from error
        raise
    if "pts_rs_login" not in text.lower():
        lock = re.search(r"<ScreenLock>\s*(\d+)\s*</ScreenLock>", text, re.I)
        hint = "（ScreenLock 只是客户端锁屏设置，不是 210064 会话上限）" if lock else ""
        raise ClientError(f"账号登录失败：{text.strip()[:300]}{hint}")
    if wait > 0:
        time.sleep(wait)


def is_session_error(error: ClientError) -> bool:
    """判断是否为会话失效类错误（可重建会话后重试），参数错误不算。"""
    text = str(error).lower()
    return "session not found" in text or "401" in text


def record_count(data) -> int:
    """估算顶层记录条数：PTS 下一级列表元素个数之和。"""
    if not isinstance(data, dict):
        return 0
    pts = data.get("PTS", data)
    if not isinstance(pts, dict):
        return 0
    return sum(len(v) for v in pts.values() if isinstance(v, list))


def handle_session(args: argparse.Namespace) -> dict:
    """按标准顺序建立会话（握手→设备登录→账号登录），保存 cookie 文件供后续命令复用。"""
    jar = load_cookie_jar(args.cookie_file)
    if has_jsessionid(jar, base_url_of(args)) and not getattr(args, "force", False):
        raise ClientError(
            "cookie 文件里已有 JSESSIONID：session 会 GET 握手并覆盖原会话，"
            "可能毁掉一个本来可用的登录态。只是查询请直接用 "
            "query --cookie-file ...（默认复用、不登录）；确认要重建再加 --force。")
    establish_session(args, jar, args.login_wait)
    transform_jsessionid(jar, getattr(args, "cookie_suffix", None))
    save_cookie_jar(jar, args.cookie_file)
    return {
        "session": "ready",
        "order": "GET 握手 → 设备登录(register) → 账号登录(login)",
        "login_wait_seconds": args.login_wait,
        "note": "会话已就绪。query/batch 对复用会话默认保留、对本次新建会话默认退出；"
                "连续查询优先复用 --cookie-file 或 --jsessionid，不要重复建会话"
                "（210064 = max_user_connection=20 会话上限，不是 10 分钟锁屏）。",
    }


def handle_batch(args: argparse.Namespace) -> dict:
    """单进程批量查询：复用会话或建会话 → 顺序查询 → 按会话来源决定是否退出。

    spec JSON 形如 {"queries": [{"category": "Csection",
    "params": {"StudyName": "A2024042-T031-01"}, "output": "路径.json"}]}。
    复用会话默认保留；本次新建（或 401 后重建）的会话默认退出。每项结果写 output 文件。
    """
    spec_path = Path(args.spec).expanduser().resolve()
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ClientError(f"无法读取批处理 spec {spec_path}：{error}") from error
    queries = spec.get("queries") if isinstance(spec, dict) else None
    if not isinstance(queries, list) or not queries:
        raise ClientError("spec 必须是 {\"queries\": [{\"category\": ..., \"params\": {...}, \"output\": ...}]}")

    url = base_url_of(args)
    rebuilds = 0

    def ensure() -> None:
        nonlocal rebuilds
        establish_session(args, jar, args.login_wait)
        rebuilds += 1

    # 会话复用：--jsessionid/非空 cookie 文件直接查询，不再重复登录——
    # 已有活跃会话时重复登录会累积占用 max_user_connection 名额。只有 401 才重建。
    jar = open_session_jar(args)
    reused_session = has_jsessionid(jar, url)
    if not reused_session:
        if getattr(args, "no_login", False):
            raise ClientError(
                "没有可用会话，且指定了 --no-login：请用 --jsessionid/--jsessionid-file "
                "或非空 --cookie-file 提供会话。")
        ensure()
    results = []
    session_invalidated = False
    for index, query in enumerate(queries, 1):
        if not isinstance(query, dict) or not query.get("category"):
            results.append({"index": index, "ok": False, "error": "查询项缺少 category"})
            continue
        category = str(query["category"])
        category_requested = category
        category = resolve_category(category)
        if args.resume and query.get("output"):
            target = Path(str(query["output"])).expanduser().resolve()
            if target.exists() and target.stat().st_size > 0:
                results.append({"index": index, "category": category,
                                "ok": True, "skipped": True, "output": str(target)})
                continue
        params = [f"{key}={value}" for key, value in (query.get("params") or {}).items()]
        body = build_xml("PTS", [f"Doctype={RQ_STUDY_DATA}", f"Category={category}", *params])
        data = None
        error = None
        for attempt in (1, 2):
            try:
                status, _, resp = send_xml(url, body, jar, args.timeout)
                text = parse_xml_response(status, resp)
                data = xml_to_json(text)
                error = None
                break
            except ClientError as caught:
                if attempt == 1 and is_session_error(caught):
                    session_invalidated = True
                    if getattr(args, "no_login", False):
                        error = f"会话失效且指定了 --no-login：{caught}"
                        break
                    try:
                        ensure()
                        continue
                    except ClientError as rebuild_error:
                        error = f"会话失效且重建失败：{rebuild_error}"
                        break
                error = str(caught)
                break
        entry = {"index": index, "category": category, "ok": error is None}
        if category != category_requested:
            entry["category_requested"] = category_requested
        if error:
            entry["error"] = error[:500]
        if data is not None:
            entry["record_count"] = record_count(data)
            if query.get("output"):
                payload = json.dumps({"success": True, "category": category,
                                      "response": data}, ensure_ascii=False, indent=2)
                # batch 的 output 是 spec 显式指定的路径，重跑/重试时覆盖更新
                try:
                    save_response(payload, str(query["output"]), overwrite=True)
                except ClientError as save_error:
                    entry["ok"] = False
                    entry["error"] = f"保存输出失败：{save_error}"[:500]
                else:
                    entry["output"] = str(Path(str(query["output"])).expanduser().resolve())
        results.append(entry)

    # 复用且没有失效/重建：保留；本次新建/重建：默认退出，避免再留孤儿会话。
    session_reused = reused_session and rebuilds == 0 and not session_invalidated
    logout_note = None
    if session_invalidated and rebuilds == 0:
        # 原会话已失效且没有重建成功：清掉本地死 cookie，别再当它是可用会话。
        clear_jsessionid(jar)
    if not args.no_logout and rebuilds > 0:
        try:
            status, _, body = send_xml(
                url, build_xml("PTS", [f"Doctype={RQ_LOGOUT}", "AccessStatus=0"]),
                jar, args.timeout)
            parse_xml_response(status, body)
            clear_jsessionid(jar, urllib.parse.urlsplit(url).hostname)
            logout_note = "已退出本次新建/重建的会话"
        except ClientError as error:
            logout_note = f"退出账号失败（可忽略）：{str(error)[:200]}"
    elif session_reused:
        logout_note = "已保留复用会话（未退出账号）"
    elif session_invalidated:
        logout_note = "复用会话已失效且未重建（没有可退出的账号会话）"
    transform_jsessionid(jar, getattr(args, "cookie_suffix", None))
    if args.cookie_file:
        save_cookie_jar(jar, args.cookie_file)
    ok_count = sum(1 for r in results if r["ok"])
    return {
        "spec": str(spec_path),
        "queries": len(results),
        "ok": ok_count,
        "failed": len(results) - ok_count,
        "session_reused": session_reused,
        "session_rebuilds": rebuilds,
        "logout": logout_note,
        "results": results,
    }


def handle_logout(args: argparse.Namespace) -> dict:
    jsessionid = jsessionid_of(args)
    uses_builtin_only = (
        bool(jsessionid)
        and jsessionid == DEFAULT_JSESSIONID
        and not getattr(args, "jsessionid", None)
        and not getattr(args, "jsessionid_file", None)
        and not env_or_none(ENV_JSESSIONID)
        and not getattr(args, "cookie_file", None)
    )
    if uses_builtin_only and not getattr(args, "force", False):
        raise ClientError(
            "当前没有显式指定会话，logout 会退出脚本内置的长期 JSESSIONID。"
            "确认要释放该名额请加 --force；否则用 --jsessionid/--jsessionid-file/"
            "--cookie-file 指定要退出的会话。")
    jar = open_session_jar(args)
    status, _, body = send_xml(base_url_of(args),
                               build_xml("PTS", [f"Doctype={RQ_LOGOUT}",
                                                 f"AccessStatus={args.access_status}"]),
                               jar, args.timeout)
    text = parse_xml_response(status, body)
    clear_jsessionid(jar, urllib.parse.urlsplit(base_url_of(args)).hostname)
    transform_jsessionid(jar, getattr(args, "cookie_suffix", None))
    save_cookie_jar(jar, args.cookie_file)
    return {"response": text}


if __name__ == "__main__":
    raise SystemExit(main())
