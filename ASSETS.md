# 素材、署名与许可

## 当前公开发布的权利状态（2026-11-03）

用户明确确认本次发布所含角色图、参考图、背景、互动差分和衍生动画允许公开分发。本记录仅基于用户确认，不表示作者身份、生成服务条款或底层授权链已独立核实。旧文档中的个人预览限制是当时的历史状态，以本节作为当前发布说明。

代码 MIT 与素材许可分离；历史第三方 MIT / CC BY-NC-SA 4.0 署名及条款保持不变。当前自定义 LicenseRef 记录不授予通用商用或再许可权，详见 [素材公开分发确认](licenses/USER-CONFIRMED-DISTRIBUTION.txt)。

鲸鱼娘的小家是独立的非官方社区同人插件，与 DeepSeek / 深度求索及以下项目均无隶属或背书关系。

代码的 MIT 许可不覆盖第三方角色素材。完整安装包包含非商业素材，不能把整个包宣传为可无条件商用。
已交付的 v0.2.0 安装包改造没有调用绘图 API，没有重新生成角色图片，也没有批量收录图集；夜景图复用项目已有的个人概念图。

## 2026-11-02：当前工作区 Q 版替换

- 来源：用户提供的 `dbbca747f21fbe0993944d132d600c338644ad6d.jpg`，完整字节保存在 `art-sources/chibi-v20261102/reference.jpg`；SHA-256：`12c5fd201fb65161b30d803a45b5fd29ff4ae6e02a3b1394d1a1c8fd86a75f5b`。原件不改动。
- 仅提取左侧正面，源图边界 `[74,86,436,568]`，输出 **362×482** 原生透明 PNG / 无损 WebP。使用背景连通区域和 6 处人工检查的呆毛/发丝空隙遮罩，单像素边缘去底色；不重绘、不拉伸、不放大，不接入侧面或背面。115608 个完全不透明像素保持 JPEG 解码后的 RGB。
- 输出及深浅底预览、遮罩、来源记录：`output/chibi-v20261102/`；可重复准备命令：`python -m tools.prepare_chibi_v20261102`，该工具仅准备图片，不自行安装。
- `chibi-neutral.webp`、`scene-chibi-neutral.webp` 使用新正面；为防止进食切回另一角色，`chibi-eat.webp`、`scene-chibi-eat.webp` 同样使用新正面。**这不是新进食差分或动画。** 源目录与 `views/home/art/` 的 4 张图逐一同步，动态资源清单的静态尺寸及摘要同步更新。
- 旧 4 张 Q 版完整备份于 `art-sources/chibi-v20261102/previous-defaults/`，下方 Sutera-Diffusus / MIT 历史署名仅适用于旧图及既有安装包，不适用于此次用户提供的新图。
- 新素材许可标记为 `LicenseRef-User-Confirmed-Distribution`；作者及底层授权链未独立核实；公开分发已由用户确认，不继承代码 MIT 或旧图授权。0 次绘图/模型请求。
- 正常比例立绘、12 张互动差分、背景与物品图均不变；Q 版显示比例仍为 0.44，自定义角色图片设置及存档不被覆盖。只更新工作区与编译页面，没有更改或覆盖 `dist/` 中的旧安装包。

## 历史 v0.2.1：仅更换正常比例角色

本次以用户提供的 `deepseek.png` 为准，仅提取左侧正面；不重新生成图片，不改变 Q 版。

| 当前文件 | 来源与处理 | 权利记录 |
| --- | --- | --- |
| `portrait.webp`、`scene-portrait.webp` | `art-sources/character-v021/reference/deepseek-v1.png`；本地背景与 24 处发丝空隙遮罩、一像素边缘去白底混合，按透明边界裁切；500×991 无损 WebP，无缩放或重绘 | `LicenseRef-User-Confirmed-Distribution`；作者及底层授权链未独立核实；公开分发已由用户确认，不沿用旧图 CC 授权，也不纳入代码 MIT |

- 原图 SHA-256：`f1dfef333d337cf949aa295b56b7ce985c4628ac9bc7ad5ede95575db6bf9e14`。
- 工具：`tools/prepare_deepseek_portrait.py`；透明 PNG/WebP、深浅底检查图及来源记录：`output/imagegen/character-v021/deepseek-front-extracted/`。
- Q 版四个运行文件、背景、物品图均未改变。旧正常比例图原样保存在 `art-sources/character-v021/previous-defaults-v020/`，下方历史署名继续适用于这些旧文件及既有安装包。
- v0.2.1 完整包使用上述新正常比例图。旧版发布文件在新版验收后按用户要求清理；下表保留历史署名，适用于保留的旧立绘备份，不是对新正常比例图的授权声明。

## 已交付 v0.2.0 安装包的历史角色与物品素材

| 本地文件（`frontend/public/art/`，发布时位于 `views/home/art/`） | 作者及来源 | 许可 | 本项目修改 |
| --- | --- | --- | --- |
| `chibi-neutral.webp` | Sutera-Diffusus，`dsh-whale-musume/assets/generated/dsh-whale-state-idle-cute.webp` | MIT，上游作者明确包含立绘 | 原文件复用 |
| `chibi-eat.webp` | Sutera-Diffusus，`dsh-whale-musume/assets/generated/dsh-whale-state-daily-eat.webp` | MIT，上游作者明确包含立绘 | 原文件复用 |
| `portrait.webp` | 世界猫；上游角色形象：ZipZipPipe / 上善无形 | CC BY-NC-SA 4.0 | 从女仆三视图裁出正面，去除与边缘连通的浅色背景，转换为 WebP；该衍生图仍以 CC BY-NC-SA 4.0 共享 |
| `room.svg`、`items/*.svg` | Whale Home Contributors | MIT | 本项目的代码绘制游戏场景与家具素材，不是 AI 生图 |

出处：

- Q 版来源项目：https://github.com/Sutera-Diffusus/dsh-whale-musume
- 固定来源提交：`236245f30f7938dd6b509b5ece227e4136bab3e3`
- 作者对代码及 92 张立绘的明确许可说明：https://github.com/Sutera-Diffusus/dsh-whale-musume/issues/17
- 原许可全文：`licenses/Sutera-Diffusus-MIT.txt`
- 世界猫三视图投稿及许可声明：https://github.com/TreapGoGo/deepseek-whale-girl/issues/66
- 用户指定的图集：https://iphsiibl.github.io/deepseek-whale-girl-gallery/
- 使用的图集原图：`docs/community/issue-66-02.webp`
- 固定图集提交：`e93bc6ec7c8c179437d6dc4d270604ac4149ced1`
- 原始图副本（源码包）：`art-sources/shijiemao-maid.webp`
- 处理方法（源码包）：`tools/prepare_portrait.py`
- CC 许可全文：`licenses/CC-BY-NC-SA-4.0.txt`
- 许可原文：https://creativecommons.org/licenses/by-nc-sa/4.0/

图集是索引而非统一许可来源。本包只使用上表列明的文件，没有把其他画师的图、其他社区二创或授权不清楚的素材自动打包。
Q 版立绘的许可记录如实保留作者说明；此处不为原作者作额外的权利保证。

## 已交付 v0.2.0 安装包的历史衍生文件

| 文件（`frontend/public/art/`，构建后同名位于 `views/home/art/`） | 来源与处理 | 权利记录 |
| --- | --- | --- |
| `night-room.webp` | 已有个人夜景概念图，1672×941，保留完整构图，不缩放不裁切，以质量 95 转换 RGB WebP | 公开分发已由用户于 2026-11-03 确认；底层授权未独立核实，不归入代码 MIT |
| `scene-portrait.webp` | 原 `portrait.webp` 按透明区域边界裁切，便于脚底定位；无损 WebP | 保持 CC BY-NC-SA 4.0 |
| `scene-chibi-neutral.webp` | 原 Q 版待机图按透明区域边界裁切，无损 WebP | 按原素材 MIT 记录 |
| `scene-chibi-eat.webp` | 原 Q 版进食图按透明区域边界裁切，无损 WebP | 按原素材 MIT 记录 |

处理脚本：`tools/prepare_scene_assets.py`。CSS 中的呼吸、位移、阴影、轻微亮度与饱和度调整只用于界面呈现。
旧正常比例立绘及其衍生文件仍共享于 CC BY-NC-SA 4.0，署名和许可文件随旧安装包提供；不适用于本次用户提供的新图。

### 夜景图来源记录

- 工作区原文件：`output/imagegen/whale-home-night-room-v1.png`，原件未覆盖。
- 源码包原件副本：`art-sources/night-room-v1.png`。
- 源文件 SHA-256：`3272ec74b024ffdb179e89ee3f6888e3c6999af65af2ce74824d717a71e87ef7`。
- 原提示与来源记录：`art-sources/night-room-v1.prompt.txt`、`art-sources/night-room-v1.provenance.json`。
- 该记录描述用户指定第三方 Images API 的历史生成过程；底层模型并未独立核实。本次不进行新请求。
- 原来源文件标注当时为“未集成的概念预览”；本版在保留原始记录的同时将 WebP 衍生图加入个人包，当前用途以本说明及素材清单为准。
- 用户选择纳入个人安装包不等于已确认第三方权利。服务条款及公开再分发条件仍待核实；不得据此宣称可自由商用或公开分享。
- 详见 `PERSONAL-USE-NOTICE.md`、`licenses/Personal-Preview-Artwork.txt`。

## v0.2.1 已发布包的完成范围

现有完整夜景背景、正常比例与 Q 版角色、三个固定站位、轻微移动与呼吸动效。
书架阅读、电脑娱乐、窗边看夜景、床边休息使用真实后端动作；立绘没有新增坐、卧、拿书差分，不能将站立形象描述为完整动作动画。
自由家具布置已移除，原家具 SVG 只用作收纳/物品库图标；旧 `room.svg` 保留在素材清单中但不用于新版房间显示。
完整表情、动作差分、家具遮挡层、昼夜变化与三维视角不属于本版交付。

个人导入的角色和物品图片只留在当前安装实例，不会进入本项目发布包。
旧自定义背景保留在数据及存档中，但本版不显示它，也不提供任意房间背景替换。
再次分享存档时，应先确认其中图片权利与个人隐私；存档可能包含聊天、记忆等信息。


## v0.3.0 个人包：12/12 张互动差分

素材源仍在 `frontend/preview-assets/art/interaction-v030`；正式构建会按摘要复制至 `views/home/art/interaction-v030`，独立预览构建则复制至 `artifacts/interaction-v030/preview-site`。不替换原默认立绘、背景或 Q 版图。

包含俏皮笑、思考、困倦、害羞、难过、摸头、收礼、白饭进食、饮茶、阅读、掌机游戏、站立休息。五种表情保留原身体及 alpha；动作图只做已审查的透明噪点清理和边距裁切，不用白色色键，不拉伸。休息为站立放松，不是假装坐卧。

游戏/休息已在 2026-11-01 的前序补图任务中生成并审查；该任务累计台账 8 次 CLI 调用，HTTP 尝试数和计费未独立核实。本次更新包体不再联网生成图片。原人物、第三方渠道底层模型及再分发权利未独立核实，仅供个人安装预览，不继承代码 MIT 或旧立绘许可。

安装包的 `asset-manifest.json` 逐一记录全部 32 张图（原有 20 张 + 12 张差分）的来源和 SHA-256。差分目录的 `manifest.json` 另含原生尺寸、脚底锚点及空缺图清单。打包器会拒绝缺图、摘要不符、陈旧构建或未审查图片。

源码包额外包含离线检查所需的明确列出的原图、参考图、提示词和不含密钥的调用/摘要审查记录；不打包整个生成输出目录、日志、凭据或个人数据库。旧 v0.2.1 安装包不变。更新说明见 `RELEASE-V030.md`。

## v0.3.2 个人包：当前 Q 版与待机动画

本次将工作区已确认的新 Q 版与正常比例 neutral 待机纳入更新包，旧安装包保持原字节。待机透明 WebP 为 500×991、120 帧、20 fps、6 秒，本地合成厚睫毛眨眼和局部呼吸。动态来源、配方和 SHA-256 单独记录在 `asset-manifest.json` 的 `character_motion` 段；仍保留 32 个静态/互动素材条目。源码包按明确白名单附带生成脚本、闭眼参考、睫毛资产、测量 JSON、六张关键帧和三份无凭据验收 JSON，不纳入本地个人数据。未完成的模型或动作没有被标为已审核。
