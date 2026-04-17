export const APPLICATION_STATUSES = ['待投递', '已投递', '笔试', '面试中', 'Offer', '已拒绝'] as const

export type ApplicationStatus = (typeof APPLICATION_STATUSES)[number]

export const STATUS_COLORS: Record<ApplicationStatus, string> = {
  待投递: 'default',
  已投递: 'processing',
  笔试: 'purple',
  面试中: 'orange',
  Offer: 'success',
  已拒绝: 'error',
}
