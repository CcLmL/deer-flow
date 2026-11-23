# brand-report-4p.pptx 使用说明

> 本说明与 `brand-report-4p.pptx` 配套。模板为**纯排版**：3 页版式骨架
> （封面 / 内容示例页 / 结尾页），**内容文字全部为空**，只有版式标签
> （"汇报人：/时 间："前缀、结尾标语）。**目录页不在模板里**，需要时按
> 第 3.4 节 recipe 自建。生成新文件时按本说明把文字写进去。
> 模板为部署方自有品牌资产，只随本 skill 内网使用，勿外发。

沙箱内路径：`/mnt/skills/public/officecli/templates/brand-report-4p.pptx`（只读）

## 1. 形状地址簿（固定 @id，直接写，不用 get 探测）

模板固定，形状路径恒定。**基础 3 页直接用下表路径，跳过 `get` 探测**：

| 页 | 形状 | 路径 | 用途 |
|---|---|---|---|
| 1 | `Textplatzhalter 1` | `/slide[1]/shape[@id=9]` | 封面标题区（3 段：主标题/副标题/——行），48pt 粗 #01699A 居中 |
| 1 | `Textplatzhalter 2` | `/slide[1]/shape[@id=10]` | "汇报人：/时 间："两行标签（值待填） |
| 2 | `标题 2` | `/slide[2]/shape[@id=3]` | 内容页标题，32pt |
| 2 | `矩形 48` | `/slide[2]/shape[@id=49]` | 内容页正文框 (0.65,1.24) 12.21×5.45 英寸 |
| 3 | 结尾标语 | `/slide[3]/shape[@id=25]` `[@id=16]` | **不动** |

第 1 页其余形状（图片占位符/多边形/logo）与第 2 页 `[@id=8]` 下划线、第 3 页全部：**不动**。

**克隆出的新页 @id 会变**（如 2097153、2097156…）：`add --from` 的回显会打印新页的
形状路径（"Copied to /slide[N]" + 形状 @id 列表），**用回显值，绝不猜**，也
**不要**把基础页的 `@id=3/@id=49` 用在克隆页上——会 "No shape found"。

## 2. 版式常量与写文字 recipe

- 字体：微软雅黑；主色 #01699A；目录绿 #4CB139
- **封面标题**（@id=9，48pt 粗 #01699A 居中已内置，写文字仍显式带样式）：
  `set "$OUT" '/slide[1]/shape[@id=9]' --prop text='第一行\n第二行' --prop font=微软雅黑 --prop size=48pt --prop bold=true --prop color=01699A`
  （`\n` 拆段；副标题行如需 "——××年度" 把 —— 写进文字）
- **汇报人/时间**（@id=10，16pt #01699A）：
  `--prop text='汇报人：张三\n时   间：2026年10月'`，同样带 font/size/color
- **内容页标题**（@id=3，32pt）：`--prop text='页面标题' --prop size=32pt --prop font=微软雅黑`
  - **⚠ 标题是 ph=title 占位符，有坑（生产实测）**：同一 batch 里先写标题再写该页正文，
    保存时标题会被版式重同步**冲掉**（set 报 success 但落盘为空）。**标题必须最后写**：
    正文等全部写完、克隆移动全部完成后，再用**单独一条 set** 写每个页标题，
    写后 `view text` 必须看到每页第一行是标题。
- **正文**（@id=49）：
  `--prop text='段1\n段2\n段3' --prop font=微软雅黑 --prop size=18pt --prop lineSpacing=1.3x`
  - 小节标题行加粗要**逐段 set**（shape 级 set 只能统一格式）：
    `set "$OUT" '/slide[N]/shape[@id=…]/paragraph[1]' --prop bold=true`（段落序号 1 起）
  - 正文**不设 color**（继承主题黑），也不要自创颜色
  - 容量约 8–10 行；超长拆页，不要压缩字号；正文不要低于 y≈6.7 英寸（页脚条在 6.92）
- **表格**（正文页放表格时）：
  `add /slide[N] --type table --prop data='列1,列2;A,1;B,2' --prop x=0.65in --prop y=1.24in --prop width=12.21in --prop height=4in`
  表头样式等按 `help pptx table` 的 banding/header 属性设一次即可，别反复查。
- 页脚/logo/标语由版式自带，不用处理

## 3. 工作流（一次批量、少往返）

```bash
OCLI='sh /mnt/skills/public/officecli/bin/officecli.sh'
OUT=/mnt/user-data/workspace/汇报.pptx
cp /mnt/skills/public/officecli/templates/brand-report-4p.pptx "$OUT"
```

### 3.1 第一笔 batch：封面 + 基础内容页

用第 1 节的地址簿路径直接写，无需 get/view：

```json
[
  {"command":"set","path":"/slide[1]/shape[@id=9]","props":{"text":"…","font":"微软雅黑","size":"48pt","bold":"true","color":"01699A"}},
  {"command":"set","path":"/slide[1]/shape[@id=10]","props":{"text":"汇报人：…\n时   间：…","font":"微软雅黑","size":"16pt","color":"01699A"}},
  {"command":"set","path":"/slide[2]/shape[@id=49]","props":{"text":"…","font":"微软雅黑","size":"18pt","lineSpacing":"1.3x"}}
]
```

```bash
$OCLI batch "$OUT" --input batch1.json --best-effort
# 标题（ph=title）单独、最后写，写后立即验证：
$OCLI set "$OUT" '/slide[2]/shape[@id=3]' --prop text='…' --prop font=微软雅黑 --prop size=32pt
$OCLI view "$OUT" text --max-lines 5   # 每页第一行必须是标题，缺了立即重写
```

**填充 batch 用 `--best-effort`**：每条独立，一条路径错不应作废整批
（原子回滚会把已成功项全部撤销，害得重写——有前车之鉴）。

### 3.2 需要更多内容页：一次命令克隆 N 页并全部移到结尾页之前

```bash
for i in 1 2 3; do $OCLI add "$OUT" / --from '/slide[2]' | tee -a clone.log; done
# 克隆页追加在末尾（含结尾页之后），看 clone.log 记下每个新页页码与形状 @id
$OCLI view "$OUT" outline
# 把各新页 move 到结尾页之前（结尾页当前是最后一页，页码以 outline 为准）
```

- `add --from '/slide[2]'` 整页复制（含全部关系，格式继承）。
- **克隆页形状路径以回显为准**（新 @id），填克隆页时用它，不要用地址簿里的 @id=3/@id=49。
- 克隆 N 页一次做完，再一次性 move，最后**一笔 batch 填完所有新页**；不要
  克隆一页填一页（来回读 outline 很贵）。

### 3.3 需要目录页时：自建（用户要求多章节/总览时再加）

在封面之后、正文之前加一页，按原品牌目录版式复刻（左侧大标题，右侧条目列）：

```bash
$OCLI add "$OUT" / --type slide --prop layout="Title and Content"
$OCLI move "$OUT" '/slide[新页]' --before '/slide[2]'
```

然后向该页加形状（batch 一次完成）：

1. 左侧大标题：`add /slide[P] --type shape --prop text='目  录' --prop x=1.41in --prop y=0.83in --prop width=3.17in --prop height=1.35in --prop font=微软雅黑 --prop size=80pt --prop bold=true --prop color=4CB139`
2. `CONTENTS` 小字：同法 `text='CONTENTS' --prop x=1.48in --prop y=2.19in --prop width=3.04in --prop height=0.61in --prop size=36pt --prop bold=true --prop color=4CB139`
3. 每个条目 i（1 起，最多 **4** 个——第 5 个会压到页脚）：
   - 序号圆角块：`--prop text='0i' --prop x=6.34in --prop y=(1.77+(i-1)*1.16)in --prop width=1.16in --prop height=0.72in --prop geometry=roundRect --prop fill=01699A --prop size=32pt --prop bold=true --prop color=FFFFFF`
     （文本居中；`roundRect` 不支持就用 `rect`，版式差异可接受）
   - 标题文字框：`--prop text='章节标题' --prop x=7.66in --prop y=(1.85+(i-1)*1.16)in --prop width=3.3in --prop height=0.57in --prop font=微软雅黑 --prop size=28pt --prop bold=true`
   - 若只有 2–3 个章节，同样从 y=1.77 起排，不必居中填空

### 3.4 QA 与交付

```bash
$OCLI validate "$OUT"
$OCLI view "$OUT" issues
$OCLI view "$OUT" text --max-lines 300
```

交付前逐页过一遍 `view text`：**每页第一行必须是页标题**（标题栏不能空——标题
被冲掉是已知坑）、无空页（克隆页都要写过文字）、小节标题已加粗，`view outline`
里结尾页在最后一页。正文超 8–10 行拆到下一页。
交付：复制到 `/mnt/user-data/outputs/`，用 present_files 呈现。

## 4. 纪律

1. 模板只读：先 `cp` 到 workspace 再改。
2. 结尾页恒在最后；克隆/移动后重读一次 `view outline` 即可，不要反复读。
3. 只动文字：主题、母版、页脚、封面右侧图片、结尾标语一律不动。
4. **别走歪路**：结果可疑就 `get` 那一个形状复查；不要 unzip/python 扒 XML、
   不要 `which soffice/libreoffice`、不要建试验文件对照——OfficeCLI 是本模板
   唯一工具，`help pptx <element>` 是唯一手册。
5. 填充类 batch 用 `--best-effort`；结构性 batch（add/remove/move）才用默认原子模式。
