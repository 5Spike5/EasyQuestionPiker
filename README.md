# EasyQuestionPicker

`EasyQuestionPicker` 是一个本地图文题目采集与预览工具。

它的工作方式不是直接依赖网页里图片的原始下载地址，而是连接你已经登录的 Chrome/Edge，模拟点击题目列表项，再把页面里已经渲染出来的 `.section-content` 提取出来：

- 纯文字内容直接保存为文本
- 含图片、公式、混排内容的分区直接截图保存
- 然后回填到本地 `JSON + 图片缓存`，在程序里做顺序编号和实时预览

## 适合的使用方式

1. 打开工具，先点“设置”
2. 填好题目列表项的 CSS 选择器
3. 点“打开浏览器”，在弹出的专用浏览器里登录
4. 打开你的接题列表页
5. 回到工具，点“采集当前页”或“采集当前题”
6. 左侧按 `1, 2, 3...` 顺序看题，右侧实时预览图文

## 现在支持

- 打开专用浏览器并保留登录态
- 模拟点击当前页题目列表项
- 提取题干、答案、解析分区
- 自动从 `1` 开始重新编号
- 本地缓存采集结果到 `captured/latest_questions.json`
- 左侧列表 + 右侧图文预览
- 搜索、刷新、重新采集
- 打包成 Windows `exe`

## 默认预览选择器

你给我的页面片段已经对应好了这几个默认值：

- 预览根节点：`.preview-body`
- 分区节点：`.preview-section`
- 分区标题：`.section-label`
- 分区内容：`.section-content`

你通常只需要额外补一个：

- 列表项 CSS 选择器：你题目列表里每一题可点击行的选择器

如果列表项里标题有单独节点，也可以再补：

- 列表标题 CSS 选择器

## 为什么不是直接下载图片 URL

因为很多题目页面不只是单张图：

- 可能有文字
- 可能有图和文字混排
- 可能有公式、表格、富文本

所以当前实现优先抓“浏览器已经渲染好的结果”：

- 文本保留文本
- 富内容直接截取 `.section-content`

这样本地预览会更接近你在网页上真正看到的样子。

## 配置文件

程序会在自身目录生成：

- `capture_config.json`
- `captured/latest_questions.json`
- `captured/assets/...`
- `.browser_profile/`

其中 `.browser_profile` 是专用浏览器的登录配置目录，登录一次后通常可以复用。

## 安装依赖

```powershell
python -m pip install -r requirements.txt
```

## 运行

```powershell
python app.py
```

## 打包成 exe

```powershell
.\build_exe.ps1
```

打包完成后：

```text
dist\EasyQuestionPicker.exe
```

## 运行稳定性

这个项目的打包脚本已经加了：

```text
--runtime-tmpdir .runtime
```

这样 `exe` 会优先在自身目录下的 `.runtime` 中解包，能避开某些机器把临时目录指到 `C:\Windows\Temp` 时的 `tkinter / init.tcl` 报错。

建议把 `exe` 放在你有写权限的普通目录中使用，不要放进受限目录。
