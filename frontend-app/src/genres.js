// 书籍分类英文 -> 中文展示映射（未收录的分类原样展示）
export const GENRE_CN = {
  'Nursery Rhyme': '童谣',
  'Folklore': '民间传说',
  'Fairy Tale': '童话',
  'Allegory': '寓意小说',
  'Children': '儿童文学',
  'Fable': '寓言',
  'Easy Reader': '入门读物',
  'Legend': '传奇故事',
  'Adventure': '冒险',
  'Science Fiction': '科幻',
  'Fantasy': '奇幻',
  'Gothic': '哥特',
  'Myth': '神话',
  'Romance': '爱情',
  'Detective': '侦探',
  'Fiction': '小说',
  'Classic': '经典',
}

export function genreCn(genre) {
  return GENRE_CN[genre] || genre || '未分类'
}
