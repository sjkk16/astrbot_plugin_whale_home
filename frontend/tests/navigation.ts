import { expect, type Page } from '@playwright/test'
export async function openSettings(page: Page, group='聊天与自主生活') {
  if (!(await page.getByRole('group',{name:'设置分类'}).isVisible())) {
    await page.getByRole('button',{name:'更多',exact:true}).click()
    await page.getByRole('button',{name:'小家设置',exact:true}).click()
  }
  await page.getByRole('group',{name:'设置分类'}).getByRole('button',{name:group,exact:true}).click()
  await expect(page.getByRole('group',{name:'设置分类'}).getByRole('button',{name:group,exact:true})).toHaveAttribute('aria-pressed','true')
}
export async function openItems(page: Page) {
  await page.getByRole('button',{name:'更多',exact:true}).click()
  await page.getByRole('button',{name:'物品',exact:true}).click()
}
export async function navigate(page: Page, label: string) {
  if(label==='小家设置') return openSettings(page)
  if(label==='物品') return openItems(page)
  await page.getByRole('button',{name:label,exact:true}).click()
}
