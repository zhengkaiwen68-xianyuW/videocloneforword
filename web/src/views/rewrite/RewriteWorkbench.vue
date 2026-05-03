<template>
  <div class="rewrite-workbench">
    <h2>重写工作台</h2>

    <el-form :model="form" label-width="100px">
      <el-form-item label="选择人格" required>
        <el-select v-model="form.persona_id" placeholder="选择人格" style="width: 100%">
          <el-option
            v-for="p in personas"
            :key="p.id"
            :label="p.name"
            :value="p.id"
          />
        </el-select>
      </el-form-item>

      <el-form-item label="原始文本" required>
        <el-input
          v-model="form.original_text"
          type="textarea"
          :rows="6"
          placeholder="输入需要重写的文本"
        />
      </el-form-item>

      <el-form-item label="钩子类型">
        <el-select v-model="form.hook_type" placeholder="选择钩子类型（可选）" clearable style="width: 100%">
          <el-option label="自动选择" value="" />
          <el-option v-for="t in hookTypes" :key="t" :label="t" :value="t" />
        </el-select>
      </el-form-item>

      <el-form-item label="选题技法">
        <el-input v-model="form.topic_technique" placeholder="选题技法关键词（可选）" />
      </el-form-item>

      <el-form-item>
        <el-button type="primary" @click="handleRewrite" :loading="loading">开始重写</el-button>
        <el-button @click="handleReset">重置</el-button>
      </el-form-item>
    </el-form>

    <!-- 重写任务 -->
    <div v-if="result" class="result-section">
      <h3>重写任务</h3>
      <el-descriptions :column="1" border>
        <el-descriptions-item label="批次ID">{{ result.batch_id }}</el-descriptions-item>
        <el-descriptions-item label="任务数量">{{ result.total_count }}</el-descriptions-item>
        <el-descriptions-item label="任务ID">
          <el-tag v-for="id in result.task_ids" :key="id" class="task-tag">{{ id }}</el-tag>
        </el-descriptions-item>
      </el-descriptions>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { personaApi, rewriteApi } from '../../api'

const loading = ref(false)
const personas = ref<any[]>([])
const result = ref<any>(null)

const hookTypes = [
  'question', 'shock', 'story', 'benefit', 'urgency', 'authority', 'empathy'
]

const form = ref({
  persona_id: '',
  original_text: '',
  hook_type: '',
  topic_technique: ''
})

const loadPersonas = async () => {
  try {
    const { data } = await personaApi.list()
    personas.value = data.personas || []
  } catch (e) {
    ElMessage.error('加载人格列表失败')
  }
}

const handleRewrite = async () => {
  if (!form.value.persona_id) {
    ElMessage.warning('请选择人格')
    return
  }
  if (!form.value.original_text) {
    ElMessage.warning('请输入原始文本')
    return
  }

  loading.value = true
  try {
    const { data } = await rewriteApi.batchProcess({
      source_texts: [form.value.original_text.trim()],
      persona_ids: [form.value.persona_id],
      locked_terms: [],
      max_iterations: 5,
      timeout_seconds: 300
    })
    result.value = data
    ElMessage.success('重写任务已创建')
  } catch (e: any) {
    ElMessage.error('重写失败: ' + (e.message || '未知错误'))
  } finally {
    loading.value = false
  }
}

const handleReset = () => {
  form.value = {
    persona_id: '',
    original_text: '',
    hook_type: '',
    topic_technique: ''
  }
  result.value = null
}

onMounted(loadPersonas)
</script>

<style scoped>
.rewrite-workbench {
  background: #fff;
  padding: 20px;
  border-radius: 8px;
}

h2 {
  margin: 0 0 20px 0;
  color: #303133;
}

.result-section {
  margin-top: 30px;
  padding-top: 20px;
  border-top: 1px solid #ebeef5;
}

.result-section h3 {
  margin-bottom: 16px;
  color: #303133;
}

.task-tag {
  margin-right: 8px;
}
</style>
