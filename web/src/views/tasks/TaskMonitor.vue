<template>
  <div class="task-monitor">
    <div class="page-header">
      <h2>任务监控</h2>
      <el-button @click="loadTasks" :loading="loading">
        <el-icon><Refresh /></el-icon>
        刷新
      </el-button>
    </div>

    <el-tabs v-model="activeTab">
      <el-tab-pane label="重写任务" name="tasks">
        <el-table :data="tasks" v-loading="loading" stripe>
          <el-table-column prop="id" label="任务ID" width="120" show-overflow-tooltip />
          <el-table-column prop="persona_name" label="人格" width="120" />
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <el-tag :type="getStatusType(row.status)">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="进度" width="200">
            <template #default="{ row }">
              <el-progress
                :percentage="row.progress || 0"
                :status="row.status === 'completed' ? 'success' : row.status === 'failed' ? 'exception' : undefined"
              />
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" width="180">
            <template #default="{ row }">
              {{ formatDate(row.created_at) }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="viewResult(row.id)" :disabled="row.status !== 'completed'">结果</el-button>
              <el-button size="small" type="danger" @click="handleDelete(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="视频任务" name="videoTasks">
        <el-table :data="videoTasks" v-loading="loading" stripe>
          <el-table-column prop="id" label="任务ID" width="120" show-overflow-tooltip />
          <el-table-column prop="url" label="视频URL" show-overflow-tooltip />
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <el-tag :type="getStatusType(row.status)">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="进度" width="200">
            <template #default="{ row }">
              <el-progress
                :percentage="row.progress || 0"
                :status="row.status === 'completed' ? 'success' : row.status === 'failed' ? 'exception' : undefined"
              />
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" width="180">
            <template #default="{ row }">
              {{ formatDate(row.created_at) }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="danger" @click="handleDeleteVideo(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- 结果对话框 -->
    <el-dialog v-model="showResult" title="任务结果" width="700">
      <template v-if="currentResult">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="任务ID">{{ currentResult.id }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="getStatusType(currentResult.status)">{{ currentResult.status }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="人格">{{ currentResult.persona_name }}</el-descriptions-item>
          <el-descriptions-item label="原始文本">
            <div class="text-content">{{ currentResult.original_text }}</div>
          </el-descriptions-item>
          <el-descriptions-item label="重写文本">
            <div class="text-content">{{ currentResult.rewritten_text }}</div>
          </el-descriptions-item>
          <el-descriptions-item label="评分" v-if="currentResult.score">
            <div>总体: {{ currentResult.score.overall || '-' }}</div>
            <div>钩子匹配: {{ currentResult.score.hook_match || '-' }}%</div>
            <div>人格一致: {{ currentResult.score.persona_consistency || '-' }}%</div>
          </el-descriptions-item>
        </el-descriptions>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { taskApi } from '../../api'

const loading = ref(false)
const activeTab = ref('tasks')
const tasks = ref<any[]>([])
const videoTasks = ref<any[]>([])
const showResult = ref(false)
const currentResult = ref<any>(null)
let refreshTimer: number | null = null

const getStatusType = (status: string) => {
  const types: Record<string, string> = {
    pending: 'info',
    running: 'warning',
    completed: 'success',
    failed: 'danger'
  }
  return types[status] || 'info'
}

const formatDate = (date: string) => {
  if (!date) return '-'
  return new Date(date).toLocaleString('zh-CN')
}

const loadTasks = async () => {
  loading.value = true
  try {
    const [tasksRes, videoTasksRes] = await Promise.all([
      taskApi.list(),
      taskApi.getVideoTasks()
    ])
    tasks.value = tasksRes.data.tasks || []
    videoTasks.value = videoTasksRes.data.tasks || []
  } catch (e: any) {
    ElMessage.error('加载失败: ' + (e.message || '未知错误'))
  } finally {
    loading.value = false
  }
}

const viewResult = async (id: string) => {
  try {
    const { data } = await taskApi.getResult(id)
    currentResult.value = data
    showResult.value = true
  } catch (e: any) {
    ElMessage.error('获取结果失败')
  }
}

const handleDelete = async (id: string) => {
  try {
    await ElMessageBox.confirm('确定要删除这个任务吗？', '确认删除', { type: 'warning' })
    await taskApi.delete(id)
    ElMessage.success('删除成功')
    loadTasks()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

const handleDeleteVideo = async (id: string) => {
  try {
    await ElMessageBox.confirm('确定要删除这个视频任务吗？', '确认删除', { type: 'warning' })
    await taskApi.deleteVideoTask(id)
    ElMessage.success('删除成功')
    loadTasks()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

// 自动刷新
onMounted(() => {
  loadTasks()
  refreshTimer = window.setInterval(loadTasks, 10000) // 每 10 秒刷新
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
  }
})
</script>

<style scoped>
.task-monitor {
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

.text-content {
  max-height: 200px;
  overflow-y: auto;
  white-space: pre-wrap;
  line-height: 1.6;
}
</style>
