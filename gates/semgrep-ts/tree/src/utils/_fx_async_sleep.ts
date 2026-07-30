// 反向样本:睡着等外部状态,而不是轮询/显式等待条件。
export async function fxWaitForBackend(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 500))
}
