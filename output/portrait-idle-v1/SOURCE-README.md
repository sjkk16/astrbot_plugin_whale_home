# 待机动画源码（v0.3.2）

源文件保持已验收版本，未重新绘图或压缩已批准的动画。依赖 Python、Pillow 与 NumPy（原制作用 Pillow 12.2 / NumPy 2.4）；NumPy 仅生成时需要，不是插件运行依赖。

- 运行 `python output/portrait-idle-v1/generate_idle.py` 可从已打包原图、测量 JSON 和闭眼参考重新生成 WebP、GIF 与检查图；输出留在此目录，不覆盖项目原图或自动更新审核清单。
- 先完成上面的生成命令（其中一项检查需要生成后的 GIF），再在本目录运行 `python -m unittest test_idle.py` 检查眼部、局部形变、固定脚底和 alpha。
- 安装时使用的已确认 WebP 位于 `views/home/art/character-motion/portrait/idle-v1.webp`；配方列出源文件及验收报告摘要。
- `keyframes/` 包含睁眼、半闭眼、闭眼、半睁眼、吸气和呼气极值。`qa/` 三份 JSON 是前序播放/解码验收记录，不冒充本次重新播放或宿主安装验收。
- 原始 GIF 留在工作区输出目录，没有塞入插件运行包。不同依赖版本重新编码可能改变摘要；重新生成不会自动获得审核通过。
- 仅供个人本地预览；未确认底层素材公开再分发权利。不是 Live2D 模型。
