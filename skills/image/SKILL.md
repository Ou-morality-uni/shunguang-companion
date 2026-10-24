---
name: shunguang-image
description: 在本机裁剪、缩放、旋转图片并转换格式，默认保存新副本。
---

先取得原图资源 ID 和版本。通过 office_files 提交 operation=edit、source、目标格式 png/jpeg/webp 和匹配扩展名的 name。

spec 示例：{"crop":[0,0,400,300],"size":[800,600],"rotate":90,"maintain_aspect":true}。

crop 是 EXIF 方向校正后的原图 x、y、宽、高，不是屏幕坐标；只能裁原图范围。size 默认保持比例，除非用户明确要求拉伸。rotate 按逆时针角度，须为 90 度整数倍。最大 1600 万像素。

PNG/WebP 尽量保留透明度；JPEG 格式不支持透明度，转换时使用白底并向用户说明。多帧图像仅处理第一帧。不能把这些基础操作称为生图、改背景或理解图片内容，相关模型能力和授权另按实际配置处理。
