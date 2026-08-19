import { Heart } from 'lucide-react'
import { isLiked, toggleLike, useUser } from '../store/likes'

export default function LikeButton({ universityId, size = 34 }: { universityId: string; size?: number }) {
  useUser() // re-render on any user change
  const on = isLiked(universityId)
  return (
    <button
      className={`like-btn${on ? ' on' : ''}`}
      aria-pressed={on}
      aria-label={on ? '取消收藏' : '收藏院校'}
      data-cursor
      style={{ width: size, height: size }}
      onClick={(e) => { e.stopPropagation(); toggleLike(universityId) }}
    >
      <Heart fill={on ? 'currentColor' : 'none'} strokeWidth={1.6} />
    </button>
  )
}