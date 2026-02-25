# 日记分析模板

## 用户画像
{profile_data}

## 待分析内容
<changed_document>
文件名: {filename}
内容:
{content}
</changed_document>

## 分析要求
请作为用户的个人日记助手，分析这篇日记内容（JSON格式返回）：

1. **mood**: 识别日记中的情绪状态（如：开心、焦虑、平静、沮丧等）
2. **summary**: 一句话总结当天的主要事件或感受
3. **workout_summary**: 根据日记中记录的训练完成情况，总结训练内容和效果
4. **action_items**: 基于日记内容提取的待办事项（没有则为空列表）
5. **reflections**: 用户在日记中的自我反思或成长点
6. **tags**: 建议 1-3 个标签用于分类

请以 JSON 格式返回结果。
