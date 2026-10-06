# Docker 本地恢复记录（2026-10-04）

Docker Desktop 曾指向 `C:/Users/zch/AppData/Local/Docker/wsl`，该引擎没有旧项目容器或卷。原数据盘仍在 `E:/docker/DockerDesktopWSL/disk/docker_data.vhdx`。

停止 Docker 后，备份 settings-store.json，再将 `CustomWslDistroDir` 恢复为 `E:/docker/DockerDesktopWSL`。重新启动后原项目 5 个容器和 pgdata/artifacts 两个卷恢复。未删除或合并 C/E 盘数据盘。

已确认原数据库含 demo 管理员、3 笔交易及 3 条持仓。升级前暂停应用进程，使用 pg_dump 自定义格式备份至 `.tmp/ledger-before-v2.dump`；Docker 设置备份在 `.tmp/docker-settings-before-restore.json`，这些本地备份不提交版本库。

后续启动：先启动 Docker Desktop，再于项目目录运行 `docker compose up -d`。查看 `docker compose ps`；页面默认 http://localhost:8000 。不要通过恢复出厂设置或 `docker compose down -v` 排查数据目录问题，这些操作可能删除数据。

## 恢复及升级结果

- 固定 Dockerfile 基础镜像为 `python:3.12-slim-bookworm`，修复 Debian 新版与 Playwright 1.51 依赖不兼容；镜像实际构建成功。
- 新增 `.dockerignore`，排除本机环境、密钥文件和备份。
- 原 Docker 数据库已备份并升级到 `0002_security_metrics`；历史账本校验通过，重算任务已执行。
- Web、PostgreSQL 健康检查正常，Worker、Scheduler 运行正常。
- 使用原 demo 账号通过真实浏览器验证登录、持仓与采集管理页面，未发现 JavaScript 错误。
- 原现金管理产品个人收益仍按设计显示缺失，未编造净值或替换原交易。

本记录更新此前 v2 文档中的“Docker 构建未验证/未迁移原库”状态：这些步骤已在用户本次明确要求恢复 Docker 并启动项目后完成，仅针对本机环境。

## 2026-10-05 恢复后复验

用户重新启动 Docker Desktop 后，确认数据目录仍为 E:/docker/DockerDesktopWSL，原 pgdata/artifacts 卷及四个常驻服务正常。Web、PostgreSQL 健康检查通过。真实 Docker 站点使用原 demo 账号完成 7 页面 × 4 档宽度的 28 项 UI 检查，无横向溢出或 JavaScript 错误；产品标题使用 rgb(232,236,242)。本轮未更改数据库、账号或 Docker 配置。
