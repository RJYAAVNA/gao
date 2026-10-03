# PWA 图标生成说明

本应用需要以下尺寸的图标：
- icon-72.png (72x72)
- icon-96.png (96x96)
- icon-128.png (128x128)
- icon-144.png (144x144)
- icon-152.png (152x152)
- icon-192.png (192x192)
- icon-384.png (384x384)
- icon-512.png (512x512)

## 使用以下 SVG 作为基础图标

保存为 icon.svg，然后使用在线工具或 ImageMagick 生成不同尺寸：

```bash
# 使用 ImageMagick 生成所有尺寸
convert icon.svg -resize 72x72 icon-72.png
convert icon.svg -resize 96x96 icon-96.png
convert icon.svg -resize 128x128 icon-128.png
convert icon.svg -resize 144x144 icon-144.png
convert icon.svg -resize 152x152 icon-152.png
convert icon.svg -resize 192x192 icon-192.png
convert icon.svg -resize 384x384 icon-384.png
convert icon.svg -resize 512x512 icon-512.png
```

或使用在线工具：
- https://realfavicongenerator.net/
- https://www.pwabuilder.com/imageGenerator

## 临时方案

在开发阶段，可以创建一个纯色占位符图标，或使用 Favicon Generator 快速生成。

基础 SVG 图标设计（金融主题）见 icon-base.svg。
