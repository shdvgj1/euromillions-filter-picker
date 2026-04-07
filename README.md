# EuroMillions Filter Picker

一个适合部署到 GitHub Pages 的轻量静态页面项目。

## 现在的结构

- 页面前端仍然是单文件 [index.html](./index.html)
- 最近开奖数据来自仓库里的 [data/draws.json](./data/draws.json)
- 全历史开奖数据来自仓库里的 [data/history-draws.json](./data/history-draws.json)
- 历史十位数组来自仓库里的 [data/tens-patterns.json](./data/tens-patterns.json)
- 历史个位数组来自仓库里的 [data/ones-patterns.json](./data/ones-patterns.json)
- [scripts/update_draws.py](./scripts/update_draws.py) 用于抓取最新 5 期 EuroMillions 开奖
- GitHub Actions 会自动更新 `data/draws.json`、`data/history-draws.json`、`data/tens-patterns.json` 和 `data/ones-patterns.json`
- GitHub Pages 负责发布站点

## 本地运行

先更新一次本地数据文件：

```bash
cd euromillions-filter-picker
python3 scripts/update_draws.py
```

然后启动一个静态文件服务：

```bash
python3 -m http.server 8000
```

打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。

如果你更习惯用项目自带的服务脚本，也可以运行：

```bash
python3 server.py --host 127.0.0.1 --port 8000
```

## GitHub Pages 自动部署

仓库里已经包含：

- [deploy-pages.yml](./.github/workflows/deploy-pages.yml)：推送到 `main` 后自动部署 GitHub Pages
- [update-draws.yml](./.github/workflows/update-draws.yml)：按法国当地时间 `Europe/Paris` 的每周三、周五 `22:00` 自动更新一次开奖数据，也可以手动触发；如果数据有变化，会自动重新发布 Pages

部署前提：

- 使用公开仓库
- 在 GitHub 仓库里启用 GitHub Pages
- Pages 的构建来源选择 `GitHub Actions`
- 在 `Settings -> Actions -> General -> Workflow permissions` 中选择 `Read and write permissions`

## 数据更新机制

- 页面打开时读取 `data/draws.json`
- 默认剔除最近 2 期
- 可切换剔除最近 1/2/3/4/5 期
- 页面包含一个“十位数组推荐”区域，基于历史十位数组做综合推荐
- 页面还包含一个“个位数组推荐”区域，基于历史主号个位数组做综合推荐
- 页面还包含一个“联合推荐（主号 + 星号）”区域，会把主号十位数组、主号个位数组、实际号码结构和星号结构一起考虑，输出最终推荐票
- GitHub Actions 会在法国当地时间 `Europe/Paris` 的每周三、周五 `22:00` 刷新数据文件
- 如果静态数据文件暂时不可用，页面会退回到内置样例

## Docker

```bash
docker build -t euromillions-filter-picker .
docker run --rm -p 8000:8000 euromillions-filter-picker
```
