import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: '/personas'
    },
    {
      path: '/personas',
      name: 'Personas',
      component: () => import('../views/personas/PersonaList.vue')
    },
    {
      path: '/personas/:id',
      name: 'PersonaDetail',
      component: () => import('../views/personas/PersonaDetail.vue')
    },
    {
      path: '/techniques',
      name: 'Techniques',
      component: () => import('../views/techniques/TechniqueList.vue')
    },
    {
      path: '/rewrite',
      name: 'Rewrite',
      component: () => import('../views/rewrite/RewriteWorkbench.vue')
    },
    {
      path: '/tasks',
      name: 'Tasks',
      component: () => import('../views/tasks/TaskMonitor.vue')
    }
  ]
})

export default router
