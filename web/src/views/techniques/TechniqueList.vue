<template>
  <div class="technique-list">
    <div class="page-header">
      <h2>技法知识库</h2>
      <div class="filters">
        <el-select v-model="filters.hook_type" placeholder="钩子类型" clearable style="width: 150px">
          <el-option label="全部" value="" />
          <el-option v-for="t in hookTypes" :key="t" :label="t" :value="t" />
        </el-select>
        <el-input v-model="filters.keyword" placeholder="搜索关键词" clearable style="width: 200px" />
        <el-button type="primary" @click="loadHooks">搜索</el-button>
      </div>
    </div>

    <el-table :data="hooks" v-loading="loading" stripe>
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column prop="persona_name" label="来源人格" width="120" />
      <el-table-column prop="hook_type" label="钩子类型" width="120">
        <template #default="{ row }">
          <el-tag :type="getHookTypeColor(row.hook_type)">{{ row.hook_type }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="pattern" label="模式" show-overflow-tooltip />
      <el-table-column prop="example" label="示例" show-overflow-tooltip />
      <el-table-column label="效果评分" width="100">
        <template #default="{ row }">
          <el-rate v-model="row.effectiveness" disabled :max="5" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="viewDetail(row.id)">详情</el-button>
          <el-button size="small" type="danger" @click="handleDelete(row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-if="total > 0"
      :current-page="filters.page"
      :page-size="filters.page_size"
      :total="total"
      layout="total, prev, pager, next"
      @current-change="handlePageChange"
      style="margin-top: 16px; justify-content: flex-end;"
    />

    <!-- 详情对话框 -->
    <el-dialog v-model="showDetail" title="钩子详情" width="600">
      <template v-if="currentHook">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="ID">{{ currentHook.id }}</el-descriptions-item>
          <el-descriptions-item label="来源人格">{{ currentHook.persona_name }}</el-descriptions-item>
          <el-descriptions-item label="钩子类型">
            <el-tag :type="getHookTypeColor(currentHook.hook_type)">{{ currentHook.hook_type }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="模式">{{ currentHook.pattern }}</el-descriptions-item>
          <el-descriptions-item label="示例">{{ currentHook.example }}</el-descriptions-item>
          <el-descriptions-item label="使用场景">{{ currentHook.use_case || '-' }}</el-descriptions-item>
          <el-descriptions-item label="效果评分">
            <el-rate v-model="currentHook.effectiveness" disabled :max="5" />
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatDate(currentHook.created_at) }}</el-descriptions-item>
        </el-descriptions>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { techniqueApi } from '../../api'

const loading = ref(false)
const hooks = ref<any[]>([])
const total = ref(0)
const showDetail = ref(false)
const currentHook = ref<any>(null)

const hookTypes = [
  'question', 'shock', 'story', 'benefit', 'urgency', 'authority', 'empathy'
]

const filters = ref({
  hook_type: '',
  keyword: '',
  page: 1,
  page_size: 20
})

const getHookTypeColor = (type: string) => {
  const colors: Record<string, string> = {
    question: '',
    shock: 'danger',
    story: 'success',
    benefit: 'warning',
    urgency: 'danger',
    authority: '',
    empathy: 'info'
  }
  return colors[type] || ''
}

const formatDate = (date: string) => {
  if (!date) return '-'
  return new Date(date).toLocaleString('zh-CN')
}

const loadHooks = async () => {
  loading.value = true
  try {
    const { data } = await techniqueApi.listHooks(filters.value)
    hooks.value = data.hooks || []
    total.value = data.total || 0
  } catch (e: any) {
    ElMessage.error('加载失败: ' + (e.message || '未知错误'))
  } finally {
    loading.value = false
  }
}

const viewDetail = async (id: string) => {
  try {
    const { data } = await techniqueApi.getHook(id)
    currentHook.value = data
    showDetail.value = true
  } catch (e: any) {
    ElMessage.error('加载详情失败')
  }
}

const handleDelete = async (id: string) => {
  try {
    await ElMessageBox.confirm('确定要删除这个钩子吗？', '确认删除', { type: 'warning' })
    await techniqueApi.deleteHook(id)
    ElMessage.success('删除成功')
    loadHooks()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error('删除失败: ' + (e.message || '未知错误'))
    }
  }
}

const handlePageChange = (page: number) => {
  filters.value.page = page
  loadHooks()
}

onMounted(loadHooks)
</script>

<style scoped>
.technique-list {
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

.filters {
  display: flex;
  gap: 12px;
}
</style>
