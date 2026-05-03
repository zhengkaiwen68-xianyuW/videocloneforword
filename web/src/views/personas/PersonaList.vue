<template>
  <div class="persona-list">
    <div class="page-header">
      <h2>人格管理</h2>
      <el-button type="primary" @click="showCreateDialog = true">
        <el-icon><Plus /></el-icon>
        创建人格
      </el-button>
    </div>

    <el-table :data="personas" v-loading="loading" stripe>
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="description" label="描述" show-overflow-tooltip />
      <el-table-column label="视频数" width="100">
        <template #default="{ row }">
          {{ row.video_count || 0 }}
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="180">
        <template #default="{ row }">
          {{ formatDate(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="250" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="viewDetail(row.id)">详情</el-button>
          <el-button size="small" type="success" @click="analyzeTechniques(row.id)">分析技法</el-button>
          <el-button size="small" type="danger" @click="handleDelete(row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 创建人格对话框 -->
    <el-dialog v-model="showCreateDialog" title="创建人格" width="500">
      <el-form :model="createForm" label-width="80px">
        <el-form-item label="名称" required>
          <el-input v-model="createForm.name" placeholder="输入人格名称" />
        </el-form-item>
        <el-form-item label="ASR文本">
          <el-input v-model="createForm.source_text" type="textarea" :rows="4" placeholder="输入已转写文本（与视频URL二选一）" />
        </el-form-item>
        <el-form-item label="视频URL">
          <el-input v-model="createForm.video_urls_text" type="textarea" :rows="3" placeholder="输入B站视频URL，一行一个（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="handleCreate" :loading="creating">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { personaApi } from '../../api'

const router = useRouter()
const loading = ref(false)
const personas = ref<any[]>([])
const showCreateDialog = ref(false)
const creating = ref(false)
const createForm = ref({
  name: '',
  source_text: '',
  video_urls_text: ''
})

const formatDate = (date: string) => {
  if (!date) return '-'
  return new Date(date).toLocaleString('zh-CN')
}

const loadPersonas = async () => {
  loading.value = true
  try {
    const { data } = await personaApi.list()
    personas.value = data.personas || []
  } catch (e: any) {
    ElMessage.error('加载失败: ' + (e.message || '未知错误'))
  } finally {
    loading.value = false
  }
}

const viewDetail = (id: string) => {
  router.push(`/personas/${id}`)
}

const analyzeTechniques = async (id: string) => {
  try {
    await personaApi.analyzeTechniques(id)
    ElMessage.success('技法分析已启动')
    loadPersonas()
  } catch (e: any) {
    ElMessage.error('分析失败: ' + (e.message || '未知错误'))
  }
}

const handleCreate = async () => {
  if (!createForm.value.name) {
    ElMessage.warning('请输入人格名称')
    return
  }
  const sourceTexts = createForm.value.source_text.trim()
    ? [createForm.value.source_text.trim()]
    : []
  const videoUrls = createForm.value.video_urls_text
    .split(/\r?\n/)
    .map(url => url.trim())
    .filter(Boolean)

  if (sourceTexts.length === 0 && videoUrls.length === 0) {
    ElMessage.warning('请输入ASR文本或视频URL')
    return
  }

  creating.value = true
  try {
    await personaApi.create({
      name: createForm.value.name.trim(),
      source_texts: sourceTexts.length ? sourceTexts : undefined,
      video_urls: videoUrls.length ? videoUrls : undefined
    })
    ElMessage.success('创建成功')
    showCreateDialog.value = false
    createForm.value = { name: '', source_text: '', video_urls_text: '' }
    loadPersonas()
  } catch (e: any) {
    ElMessage.error('创建失败: ' + (e.message || '未知错误'))
  } finally {
    creating.value = false
  }
}

const handleDelete = async (id: string) => {
  try {
    await ElMessageBox.confirm('确定要删除这个人格吗？', '确认删除', { type: 'warning' })
    await personaApi.delete(id)
    ElMessage.success('删除成功')
    loadPersonas()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error('删除失败: ' + (e.message || '未知错误'))
    }
  }
}

onMounted(loadPersonas)
</script>

<style scoped>
.persona-list {
  background: #fff;
  padding: 20px;
  border-radius: 8px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.page-header h2 {
  margin: 0;
  color: #303133;
}
</style>
