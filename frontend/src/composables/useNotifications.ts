import { ElNotification, type NotificationOptions } from 'element-plus'

export function useNotifications() {
  function notify(message: string, options: Partial<NotificationOptions> = {}) {
    ElNotification({
      title: options.title || 'ChargeOps',
      message,
      type: options.type || 'info',
      duration: options.duration ?? 3500,
      ...options,
    })
  }

  return { notify }
}

