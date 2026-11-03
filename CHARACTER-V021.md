# v0.2.1 角色外貌制作记录

> 后续更新（2026-11-02）：当前工作区 Q 版已改为用户新提供三视图的左侧正面，见 `ASSETS.md`。下文“Q 版不变”和“尚未接入”仅记录 v0.2.1 当时的阶段；之前准备的 Q 版候选仍保留，但未用于这次替换。

## v0.2.1 完整个人包

本版将已确认的 deepseek.png 正常比例形象纳入完整插件包，Q 版素材、比例与显示逻辑保持不变。统一版本号为 0.2.1，不修改 API、数据格式或个人自定义图片设置。
素材备份和下方制作记录继续保留；仅在新版验收通过后清理旧版安装包、源码包与校验文件。完整包验证结果见 `VERIFICATION.md`。 本版发布验收为 191 项 Python 测试、19 项浏览器测试，以及隔离 AstrBot 的全新安装和 v0.2.0 → v0.2.1 升级；另补充 iframe 请求序列化修复，保证设置保存可用。

## 历史制作阶段：deepseek.png 正常比例角色接入，Q 版不变

2026-10-31，用户要求继续调整正常比例角色、明确不改 Q 版，并提供新的 `deepseek.png` 三视图。本次仅取左侧正面，替换工作区及构建页面的 `portrait.webp`、`scene-portrait.webp`。下方各阶段“尚未接入”等表述为当时的历史状态；当前完整包状态以上方版本说明为准。

- 新原图 1536×1024，原样归档为 `art-sources/character-v021/reference/deepseek-v1.png`；下载目录原件不改动。SHA-256：`f1dfef333d337cf949aa295b56b7ce985c4628ac9bc7ad5ede95575db6bf9e14`。
- 使用独立、来源摘要固定的遮罩，只清理画布和 24 处已检查的发丝/袖口背景空隙；白色围裙、袜子、眼睛高光保留，一像素边缘恢复透明混合。透明成品 500×991，原生尺寸，不缩放、不改变姿势、不重绘脸部或服装。
- 工具：`tools/prepare_deepseek_portrait.py`。成品、深浅底检查图及来源记录：`output/imagegen/character-v021/deepseek-front-extracted/`。该工具仅准备素材，不会自行安装或触碰 Q 版。
- 旧默认正常比例图片完整保存在 `art-sources/character-v021/previous-defaults-v020/`；之前的成熟版和 Q 版提取成果也保留原样。
- 房间正常比例立绘与聊天面板立绘同步更新；既有用户自定义角色图片设置不被清空。Q 版四个运行素材、显示代码、0.44 比例与进食图不更改。没有新增侧面/背面切换或动作差分。
- 本次 0 次绘图 API 请求、不使用凭证、不联网生成。原图作者和公开再分发权利未核实，维持个人预览范围；新图不继承旧图 CC 授权。
- 版本号、存档结构和 `dist/` 既有安装包保持不变，本次不打包或发布。
- 验证：173 项 Python 测试、17 项无头 Edge 浏览器测试、Ruff、Vue 类型检查及 Vite 构建全部通过。新增 34 项 Python 检查与 2 项浏览器测试。276653 个完全不透明像素保持原图 RGB，PNG/WebP 的透明度与全部可见像素一致。
- 已人工查看深浅底检查图和窗边、书桌、床边、聊天面板、390px 手机端、Q 版实际浏览器截图；前后摘要对比仅 4 个正常比例运行文件变化，其余 44 个跟踪文件不变。记录：`artifacts/portrait-deepseek/verification.json`；截图同目录。截图来自隔离的本地演示，不是在线模型或 AstrBot 宿主验收。

## Q 版参考图正面提取（已准备，尚未接入）

**Q 版已准备，尚未接入。** 使用用户提供的 `dafeiyu-chibi-character-sheet.png`，只提取左上角正面，不重新生成或重绘。

- 原图以完整字节归档至 `art-sources/character-v021/reference/chibi-character-sheet-v1.png`；下载目录原文件保持不变。SHA-256：`539548dbdf78a6488b9baca3af07521fe422c62bd8dee6e5664a1880754325b6`。
- 成品及预览统一位于 `output/imagegen/character-v021/chibi-reference-extracted/`。透明 PNG 和无损 WebP 为 `chibi-reference-v1.*`，原生 **526×600**，不放大、不拉伸。
- 使用独立的 Q 版遮罩，处理白色画布、11 处已核对的背景空隙和原图地面投影。只在一像素轮廓边缘恢复透明混合；保留脸、表情、动作、服装和鲸尾原貌，白色衣物与眼睛高光不透明。
- 已检查深色、浅色背景和呆毛、发丝、裙边、尾鳍、鞋底细节。189727 个完全不透明像素的 RGB 与原图一致；PNG/WebP 的全部可见像素及透明度一致。
- 房间预览为**静态合成，不是实际应用截图**：保持原房间画面，按窗边站位和现有 Q 版 0.44 比例显示；近似夜景色调与接地阴影仅用于预览，不写入透明成品。
- 完整原图（含侧面、背面与细节）、前景遮罩、来源和处理记录一并保存。侧面和背面未单独抠图。
- 本次 **0 次绘图 API 请求，不使用凭证**。139 项 Python 测试全部通过（新增 15 项 Q 版提取测试），Ruff 通过；核验的 84 个旧交付/运行文件摘要未改变。详见成品目录的 `verification.json`。
- 工具：`python tools/prepare_reference_chibi.py`。输入摘要不符或已有输出内容冲突时停止；重复运行输出一致，不覆盖旧成果。
- 当前仍为 v0.2.0；默认角色、成熟版素材、存档、版本号和安装包不变，本次未做前端接入或浏览器验收。原图提供不等于公开再分发授权，保持个人预览范围。

## 参考图确认后的成熟版提取

用户确认以参考图左侧人物为准。已完成**本地透明提取，不是再次生成或重绘**：

- 成熟版：`output/imagegen/character-v021/reference-extracted/portrait-reference-v1.png` 与同名无损 WebP，原生 380×1033 像素，无放大或缩放。
- 原始参考图及其三视图原件原样保留，没有重复调用 API 生成三视图。
- 仅做背景分区、已核对的发丝间隙/双腿间隙去底、地面阴影移除，以及一像素边缘透明混合处理；未修改脸、手势或服装设计，不将白色衣物整体去除。
- 使用源码固定摘要与专用遮罩，输入图变动会停止。脸部、白色服装样本区以及全部完全不透明像素均经像素对比，保留原图 RGB。
- 本次 0 次 API 请求；之前两次生成尝试与记录不变。原参考图未被改写。
- 已检查深浅背景预览和按现有站位比例合成的房间预览。房间图是静态合成，不是实际应用截图。
- 该阶段 124 项 Python 测试与 Ruff 检查通过，新增 6 项提取测试；当时仅准备好成熟版。后续 Q 版提取进度见上节，前端默认素材和安装包仍未更新。
- 工具：`python tools/prepare_reference_portrait.py`；来源、遮罩和处理记录随输出保存。用户提供图片不等于已获得公开再分发授权，保持个人预览范围。

## 历史生成状态

**制作未完成，当前插件仍为 v0.2.0。未切换默认角色，未生成 v0.2.1 安装包。**

- 已原样保存用户提供的 Q 版与成熟版设定，并拆分为三份实际请求提示词。
- 已实现独立开发工具 `tools/generate_character_assets.py`，不修改系统图像工具，不向插件运行时添加绘图调用。
- 模型保持 `gpt-image-2.5-sunburst`。首次失败请求使用 `max`；用户最新要求改为 `high`，已获重新调用授权，high 修订版保留第一次失败记录，总请求上限为四次。第三方服务的底层模型和实际质量未独立验证。
- 本轮第一张成熟立绘请求于 2026-10-31 19:52:18（Asia/Shanghai）发起，发生连接/传输异常，未收到可用图片。
- 生成记录目前累计 **2 次尝试，1 张成熟版原图**：首次 max 连接失败；经用户授权的 high 于 2026-10-31 20:09:08 发起、20:10:27 收到并保存图片后未通过验收。没有提交 Q 版或设定图，计费金额未经核实。
- high 原图为 1024×1536 RGBA PNG；接口没有回显实际模型、质量、背景参数，因此只记录请求值，不宣称底层模型已验证。
- 主要视觉不符为裙摆偏短（前摆在膝盖以上，而非小腿中段）。边缘校验发现 alpha=1/255 的极淡杂点触及左侧；深浅底复核未发现人物主体明显裁切，不应把这项自动检查直接描述为鲸尾被截断。
- 本次 high 原图、来源与拒绝原因保存在 `output/imagegen/character-v021/high/`，页面未替换，新安装包未生成。
- 随后两次不带凭证、只读的模型目录连通性检查均得到 HTTP 401，说明检查时地址可达且要求认证；这不能证明生成接口可用，也不能解释先前异常。
- 用户后续明确提供临时凭证，实际通过不回显输入在生成进程内使用；未写入脚本、环境变量、请求文件或日志。推荐任务结束后撤销临时凭证。

## 固定成品

| 文件 | 请求参数 | 用途 |
| --- | --- | --- |
| `portrait.png` | 1024×1536，透明，high | 正常比例角色和聊天立绘 |
| `chibi.png` | 1024×1024，透明，high | Q 版所有活动状态 |
| `reference-sheet.png` | 1536×1024，不透明白底，high | 成熟版正、侧、背三视图与细节 |

生成目录为 `output/imagegen/character-v021/`。原始用户提示词位于
`art-sources/character-v021/prompts/`，实际请求的提示词及无凭证请求 JSON 已保存到生成目录。
不增加服饰或动作差分；保留 Q 版短裙与成熟版长裙的区别。

## 开发工具与费用保护

以下命令均在项目根目录运行；可将 `python` 换成虚拟环境中的 Python。

```shell
# 默认只整理/校验提示词，不联网，不需要密钥。
python tools/generate_character_assets.py plan --revision high
python tools/generate_character_assets.py status --revision high

# 新工作流的显式执行入口。仅从专用环境变量读取密钥。
python tools/generate_character_assets.py generate --revision high --execute

# 仅在用户明确授权临时凭证后使用；不回显、不落盘。
python tools/generate_character_assets.py generate --revision high --execute --temporary-key
```

常规密钥变量为 `WHALE_HOME_IMAGE_API_KEY`，不读取通用 `OPENAI_API_KEY`，也不接受命令行密钥值。
此工具不能静默重试已失败的本轮请求：原 max 修订版仍因失败记录而停止。获用户授权的 high 修订版使用独立输出目录，但将原失败计入总上限；high 内仍然失败即停。
**不要删除生成记录、另换目录或修改上限来绕过用户授权。** 如需重试，应先获得新的调用次数授权，并保留旧尝试记录。

保护措施：

- high 修订版每种成品固定一张，依次提交，最多三次新请求；连同原 max 失败尝试，总上限为四次，发送前持久化计数。
- 独占工作流锁；重复执行、进程中断及未知结果均不会自动重发。
- 网络层重试次数为零，不跟随重定向，不下载接口返回的任意 URL。
- 出错只记录固定错误码及允许的异常类别，不输出服务商原始错误正文、请求头或凭证。
- 若收到图片但透明通道、尺寸或返回参数不合格，保留原始结果并停止，不去白伪造透明、不自动降档重绘。
- 提示词和已完成输出以摘要绑定，不覆盖原图或旧素材。

## 视觉验收与素材准备

必须先逐张查看实际图片；技术检查不能代替人工检查角色轮廓、脚底、服装和三视图一致性。
只有三张图片均生成成功、逐项验收且摘要匹配，才允许准备新静态素材。

```shell
python tools/generate_character_assets.py review --revision high --asset portrait --checked framing --checked identity --checked clothing --checked background --checked feet_or_views --note "填写实际观察结果"
python tools/generate_character_assets.py review --revision high --asset chibi --checked framing --checked identity --checked clothing --checked background --checked feet_or_views --note "填写实际观察结果"
python tools/generate_character_assets.py review --revision high --asset reference-sheet --checked framing --checked identity --checked clothing --checked background --checked feet_or_views --note "填写实际观察结果"
python tools/generate_character_assets.py prepare-assets --revision high
```

准备步骤只生成 `scene-portrait-v021.webp` 与 `scene-chibi-v021.webp`，保留透明通道、按透明边界裁切、无损 WebP、不缩放。
原图、实际提示词、来源记录和验收摘要将归档到 `art-sources/character-v021/`。
`release.json` 仅在全部条件满足后产生。准备工具本身不会修改前端默认路径、版本号或存档。

后续待完成：接入新默认图；移除 Q 版活动对旧进食图的引用；更新个人预览素材说明；升版到 0.2.1；构建、浏览器视觉验收、隔离 AstrBot 安装与升级验证、打包。
旧角色来源和许可仍适用于现有素材，不作为尚未生成的新素材的授权。

## 验证

`tests/test_character_artwork.py` 使用本地合成 PNG 和模拟 HTTP 响应，不调用真实服务，也不把测试图用作成品。
覆盖参数与调用顺序、三次上限、失败不重试、超时与重定向、凭证脱敏、透明通道、原图保留、原提示词校验、并发锁、摘要绑定验收和无损白色衣物保留。

旧安装包和关键运行文件的制作前摘要保存在 `artifacts/character-v021/before.json`，用于核验未覆盖旧版本。

### 本次实际检查结果

- Python：118 项测试通过（包括 35 项绘图工具测试）。
- Ruff：通过。
- Vue / TypeScript 类型检查与 Vite 构建：通过。
- 现有 v0.2.0 页面流程：15 项浏览器测试通过；不是新角色的视觉验收。
- 现有 20 个展示素材的摘要与许可清单审计：通过，未重新打包。
- 15 个制作前保留文件（包括所有旧安装包和关键运行文件）的摘要未改变。
- 新图片验收：成熟版已检查但裙长不符合要求；其他两张尚未生成。v0.2.1 安装/升级验证及打包未执行，旧版本保留。

## high 档重试记录

最新请求保存在 `output/imagegen/character-v021/pending-high/`。模型、尺寸、透明背景和原提示词均未改变，只调整质量为 high。原 max 请求和失败记录保持原样。

用户随后明确要求重新调用，现已将总上限确认为四次（原 max 失败一次，加 high 最多三次）。授权记录为 `output/imagegen/character-v021/high-authorization.json`，实际 high 请求和输出位于 `output/imagegen/character-v021/high/`；`pending-high/` 作为此前准备记录保留。每次执行均重新核验旧请求记录摘要，不能清空或忽略原失败。
