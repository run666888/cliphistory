# ClipHistory · 剪贴板历史

Windows 上的剪贴板历史小工具：后台静默记录你复制过的**文本**，按时间倒序浏览、搜索，选中一条即可回填到剪贴板并自动粘回原来的窗口。

## 功能

- 轻量自绘窗口（tkinter），无第三方依赖，纯标准库
- 文本去重、截断标记、本地 JSON 持久化
- 搜索过滤、点击回填、Esc 关闭
- 单实例运行，`run.bat` 用 `pythonw` 静默启动

## 运行

```bat
run.bat
```

或：

```bash
python -m cliphistory
```

## 结构

```
cliphistory/
  app.py          窗口与交互
  store.py        JSON 持久化
  platform_win.py Windows 剪贴板 / 前台窗口 / 粘贴
  paths.py        数据目录
  selftest.py     自检
```

## License

MIT
