# 文档分析模板

## 用户画像
{profile_data}

## 待分析内容
<changed_document>
文件名: {filename}
内容:
{content}
</changed_document>

## 分析要求
请简要分析（JSON格式返回）：
1. summary: 一句话总结核心内容。
2. action_items: 提取出的明确待办事项列表（没有则为空列表）。
3. tags: 建议的 1-3 个标签。
