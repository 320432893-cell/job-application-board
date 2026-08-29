# GitHub 上传与上交流程

## 一、先确认项目能正常运行

在项目目录执行：

```bash
npm install
npm run build
```

如果构建通过，再进行上传。

## 二、初始化 Git（如果还没初始化）

在项目目录执行：

```bash
git init
git add .
git commit -m "初始化求职申请管理看板项目"
```

## 三、在 GitHub 新建仓库

去 GitHub 创建一个新仓库，仓库名建议：

```text
job-application-board
```

创建时建议：
- 不要勾选初始化 README
- 不要勾选 .gitignore
- 不要勾选 license

因为本地已经有完整项目了。

## 四、绑定远程仓库并推送

把下面命令里的仓库地址替换成你自己的：

```bash
git remote add origin https://github.com/你的用户名/job-application-board.git
git branch -M main
git push -u origin main
```

## 五、如果想让我直接协助你上传到 GitHub

你可以直接在对话里这样说：

```text
帮我提交到 git 并推到 GitHub
```

或者更明确一点：

```text
帮我把当前项目提交，仓库地址是 https://github.com/你的用户名/job-application-board.git，然后推送到 main
```

我可以协助你的内容包括：
- 检查当前变更
- 帮你整理 commit message
- 执行 `git add` 和 `git commit`
- 绑定远程仓库
- 执行 `git push`

但有两个前提：
1. 你要明确授权我执行 git 提交和推送
2. 如果本机还没登录 GitHub，可能需要你自己先完成登录

### 如果需要你自己先登录

你可以在 Claude Code 里输入：

```bash
! gh auth login
```

或者如果你已经安装并使用 Git 凭证，也可以直接推送。

### 推荐你在对话里这样说

```text
1. 帮我检查当前项目是否适合提交
2. 帮我生成 commit message
3. 帮我提交到 git
4. 帮我推送到这个仓库：https://github.com/你的用户名/job-application-board.git
```

这样我就可以一步一步带你完成。

## 六、建议上传哪些内容

建议保留：
- 源代码
- README.md
- PM-面试讲解稿.md
- GitHub-上传与上交流程.md
- package.json
- 配置文件

不建议上传：
- node_modules
- dist
- 本地编辑器配置
- 临时缓存文件
- `.claude`
- `.ai`

## 七、建议仓库首页怎么展示

仓库上传后，GitHub 首页会默认展示 README.md。

建议你的 README 重点包含：
- 这是什么项目
- 解决什么问题
- 核心功能
- 技术栈
- 本地启动方式
- 项目亮点

这样面试官打开仓库就能快速理解。

## 八、上交时可以怎么发

如果是发给老师、面试官或招聘方，可以直接发：

### 方式 1：发 GitHub 仓库链接
```text
这是我的产品经理面试作品项目：
https://github.com/你的用户名/job-application-board
```

### 方式 2：同时附一句说明
```text
这是我独立完成的求职申请管理看板项目，主要想展示我在产品结构设计、用户场景拆解和功能落地上的思考。
```

## 九、如果对方要求压缩包

可以在项目根目录压缩时排除这些内容：
- node_modules
- dist
- .git

保留源码和文档即可。

## 十、最后检查清单

上交前建议检查：

- README 是否完整
- 项目名称是否统一
- 页面文案是否已收尾
- 示例数据是否可展示
- `npm run build` 是否通过
- GitHub 仓库是否公开或已正确授权访问
