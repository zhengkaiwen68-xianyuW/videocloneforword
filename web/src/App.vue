<template>
  <el-container class="app-container">
    <el-aside width="200px">
      <div class="logo">
        <h2>人格引擎</h2>
      </div>
      <el-menu
        :default-active="route.path"
        router
        class="side-menu"
      >
        <el-menu-item index="/personas">
          <el-icon><User /></el-icon>
          <span>人格管理</span>
        </el-menu-item>
        <el-menu-item index="/techniques">
          <el-icon><MagicStick /></el-icon>
          <span>技法知识库</span>
        </el-menu-item>
        <el-menu-item index="/rewrite">
          <el-icon><Edit /></el-icon>
          <span>重写工作台</span>
        </el-menu-item>
        <el-menu-item index="/tasks">
          <el-icon><List /></el-icon>
          <span>任务监控</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-main>
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router'
import { User, MagicStick, Edit, List } from '@element-plus/icons-vue'

const route = useRoute()
</script>

<style scoped>
.app-container {
  height: 100vh;
}

.el-aside {
  background: #304156;
  color: #bfcbd9;
}

.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #263445;
}

.logo h2 {
  color: #fff;
  font-size: 18px;
  margin: 0;
}

.side-menu {
  border-right: none;
  background: #304156;
}

.side-menu .el-menu-item {
  color: #bfcbd9;
}

.side-menu .el-menu-item:hover,
.side-menu .el-menu-item.is-active {
  background: #263445;
  color: #409eff;
}

.el-main {
  background: #f5f7fa;
  padding: 20px;
}
</style>
