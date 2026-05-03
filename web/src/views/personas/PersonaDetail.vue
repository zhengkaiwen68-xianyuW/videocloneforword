<template>
  <div class="persona-detail" v-loading="loading">
    <div class="page-header">
      <el-button @click="router.back()">返回</el-button>
      <h2>{{ persona?.name || '人格详情' }}</h2>
    </div>

    <template v-if="persona">
      <el-descriptions :column="2" border>
        <el-descriptions-item label="ID">{{ persona.id }}</el-descriptions-item>
        <el-descriptions-item label="名称">{{ persona.name }}</el-descriptions-item>
        <el-descriptions-item label="描述" :span="2">{{ persona.description || '-' }}</el-descriptions-item>
        <el-descriptions-item label="视频数">{{ persona.video_count || 0 }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatDate(persona.created_at) }}</el-descriptions-item>
      </el-descriptions>

      <!-- 技法画像 -->
      <div class="section" v-if="techniques">
        <h3>技法画像</h3>
        <el-tabs>
          <el-tab-pane label="选题技法">
            <div v-if="techniques.topic_techniques?.length">
              <div v-for="t in techniques.topic_techniques" :key="t.category" class="technique-item">
                <el-tag>{{ t.category }}</el-tag>
                <span>{{ t.description }}</span>
              </div>
            </div>
            <el-empty v-else description="暂无选题技法" />
          </el-tab-pane>
          <el-tab-pane label="钩子技法">
            <div v-if="techniques.hook_techniques?.length">
              <div v-for="h in techniques.hook_techniques" :key="h.hook_type" class="technique-item">
                <el-tag type="success">{{ h.hook_type }}</el-tag>
                <span>{{ h.pattern }}</span>
              </div>
            </div>
            <el-empty v-else description="暂无钩子技法" />
          </el-tab-pane>
          <el-tab-pane label="结构模式">
            <div v-if="techniques.structure_patterns?.length">
              <div v-for="s in techniques.structure_patterns" :key="s.pattern_type" class="technique-item">
                <el-tag type="warning">{{ s.pattern_type }}</el-tag>
                <span>{{ s.description }}</span>
              </div>
            </div>
            <el-empty v-else description="暂无结构模式" />
          </el-tab-pane>
        </el-tabs>
      </div>

      <!-- 视频列表 -->
      <div class="section">
        <h3>关联视频</h3>
        <el-button size="small" type="primary" @click="showAddVideo = true">添加视频</el-button>
        <el-table :data="persona.videos || []" style="margin-top: 10px">
          <el-table-column prop="url" label="视频URL" show-overflow-tooltip />
          <el-table-column prop="title" label="标题" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.processed ? 'success' : 'info'">
                {{ row.processed ? '已处理' : '待处理' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </template>

    <!-- 添加视频对话框 -->
    <el-dialog v-model="showAddVideo" title="添加视频" width="500">
      <el-form label-width="80px">
        <el-form-item label="视频URL" required>
          <el-input v-model="newVideoUrl" type="textarea" :rows="3" placeholder="输入B站视频URL，一行一个" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddVideo = false">取消</el-button>
        <el-button type="primary" @click="handleAddVideo" :loading="addingVideo">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { personaApi } from '../../api'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const persona = ref<any>(null)
const techniques = ref<any>(null)
const showAddVideo = ref(false)
const newVideoUrl = ref('')
const addingVideo = ref(false)

const formatDate = (date: string) => {
  if (!date) return '-'
  return new Date(date).toLocaleString('zh-CN')
}

const loadPersona = async () => {
  loading.value = true
  try {
    const id = route.params.id as string
    const { data } = await personaApi.get(id)
    persona.value = data
  } catch (e: any) {
    ElMessage.error('加载失败: ' + (e.message || '未知错误'))
  } finally {
    loading.value = false
  }
}

const loadTechniques = async () => {
  try {
    const id = route.params.id as string
    const { data } = await personaApi.getTechniques(id)
    techniques.value = data
  } catch (e) {
    // 技法可能不存在，忽略错误
  }
}

const handleAddVideo = async () => {
  if (!newVideoUrl.value) {
    ElMessage.warning('请输入视频URL')
    return
  }
  addingVideo.value = true
  try {
    const id = route.params.id as string
    const videoUrls = newVideoUrl.value
      .split(/\r?\n/)
      .map(url => url.trim())
      .filter(Boolean)
    await personaApi.addVideo(id, { video_urls: videoUrls })
    ElMessage.success('添加成功')
    showAddVideo.value = false
    newVideoUrl.value = ''
    loadPersona()
  } catch (e: any) {
    ElMessage.error('添加失败: ' + (e.message || '未知错误'))
  } finally {
    addingVideo.value = false
  }
}

onMounted(() => {
  loadPersona()
  loadTechniques()
})
</script>

<style scoped>
.persona-detail {
  background: #fff;
  padding: 20px;
  border-radius: 8px;
}

.page-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
}

.page-header h2 {
  margin: 0;
  color: #303133;
}

.section {
  margin-top: 24px;
}

.section h3 {
  margin-bottom: 12px;
  color: #303133;
}

.technique-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid #ebeef5;
}
</style>
