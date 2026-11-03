import {
  Armchair, BedDouble, BookOpen, Box, Cloud, Coffee, Cookie, Gamepad2, LampDesk,
  Package, RectangleHorizontal, Sprout, Table2, Utensils,
} from '@lucide/vue'

export const itemIcons: Record<string, typeof Package> = {
  'armchair': Armchair, 'bed-double': BedDouble, 'book-open': BookOpen,
  'cloud': Cloud, 'cup-soda': Coffee, 'cookie': Cookie, 'gamepad-2': Gamepad2,
  'lamp-desk': LampDesk, 'package': Package, 'rectangle-horizontal': RectangleHorizontal,
  'sprout': Sprout, 'table-2': Table2, 'utensils': Utensils, 'box': Box,
}
export const activityNames: Record<string, string> = {
  idle: '自在发呆', move: '窗边看夜景', eat: '好好吃饭', drink: '喝口热茶',
  read: '沉浸阅读', play: '快乐放松', rest: '床边休息',
}
export const usageNames: Record<string, string> = {
  eat: '吃', drink: '喝', read: '阅读', play: '玩耍', rest: '休息', decorate: '装饰',
}
