// Компоненты веба 1:1 по классам design/ui.css. Стили — `@sosed/ui-web/styles.css`.
export type { AvatarPalette, AvatarProps, AvatarSize } from './Avatar.tsx';
export { Avatar, initials, paletteFor } from './Avatar.tsx';
export type { BadgeTone } from './Badge.tsx';
export { Badge } from './Badge.tsx';
export type { ButtonProps, ButtonVariant, IconButtonProps, LinkButtonProps } from './Button.tsx';
export { Button, IconButton, LinkButton } from './Button.tsx';
export type { CardProps } from './Card.tsx';
export { Card } from './Card.tsx';
export type { BubbleProps, ComposerProps } from './Chat.tsx';
export { Bubble, ChatList, Composer, MASK, MaskedText, SystemNote } from './Chat.tsx';
export type { ChipProps } from './Chips.tsx';
export { AvatarStack, Chip, Chips, Price } from './Chips.tsx';
export { cx } from './cx.ts';
export type { BannerTone, EmptyTone } from './Feedback.tsx';
export { Banner, EmptyState, ProgressBar, Skeleton, Stars, Steps, Toast } from './Feedback.tsx';
export type { CheckboxProps, OptionProps, SegmentLink, SegmentedOption } from './form/Choice.tsx';
export {
  CheckButton,
  Checkbox,
  Option,
  RadioGroup,
  RadioRow,
  Segmented,
  SegmentedNav,
  Switch,
} from './form/Choice.tsx';
export type {
  FieldProps,
  InputProps,
  PickerButtonProps,
  SearchFieldProps,
  TextareaProps,
} from './form/Field.tsx';
export { Field, Input, PickerButton, SearchField, Textarea } from './form/Field.tsx';
export type { FeedRowProps, RowProps } from './Group.tsx';
export { FeedRow, Group, NumIcon, Row, RowIcon, Tile, Tiles, UnreadDot } from './Group.tsx';
export type { JobCardBadge, JobCardProps, JobSlots } from './JobCard.tsx';
export { JobCard } from './JobCard.tsx';
export type { MapPreviewProps } from './MapPreview.tsx';
export { MapPreview } from './MapPreview.tsx';
export type { PhotoFit, PhotoProps, PhotoVariant } from './Photo.tsx';
export { Photo } from './Photo.tsx';
export type { SkeletonTextSize } from './Skeletons.tsx';
export {
  ChipSkeleton,
  RowsSkeleton,
  SkeletonCard,
  SkeletonText,
  TileSkeleton,
} from './Skeletons.tsx';
export {
  ChatSkeleton,
  FieldSkeleton,
  JobCardSkeleton,
  SpecialistCardSkeleton,
} from './CardSkeletons.tsx';
export type { RatingProps } from './Rating.tsx';
export { MetaLine, Rating } from './Rating.tsx';
export type { SheetProps } from './Sheet.tsx';
export { Sheet } from './Sheet.tsx';
export type { SpecialistBadge, SpecialistCardProps } from './SpecialistCard.tsx';
export { SpecialistCard } from './SpecialistCard.tsx';
export type { IconName, IconProps, IconSize } from './icon/Icon.tsx';
export { ICON_NAMES, Icon } from './icon/Icon.tsx';
export type { Gap } from './layout/Stack.tsx';
export { HStack, Stack } from './layout/Stack.tsx';
export type { TabBarProps, TabItem } from './TabBar.tsx';
export type { TimelineItem, TimelineState } from './Timeline.tsx';
export { Timeline } from './Timeline.tsx';
export { TabBar } from './TabBar.tsx';
export type { VideoPlayerProps } from './VideoPlayer.tsx';
export { VideoPlayer } from './VideoPlayer.tsx';
export type {
  AddTileProps,
  FailedTileProps,
  UploadTileProps,
  UploadingTileProps,
} from './Upload.tsx';
export { AddTile, UploadTile } from './Upload.tsx';
export type { HeadingProps, HeadingVariant, TextVariant } from './text/Heading.tsx';
export { Heading, SectionTitle, Text } from './text/Heading.tsx';
export type { MarkdownBlocksProps, MarkdownProps } from './text/Markdown.tsx';
export { Markdown, MarkdownBlocks } from './text/Markdown.tsx';
export type { Block as MarkdownBlock, Inline as MarkdownInline } from './text/markdown.ts';
export { inlineText, parseInline, parseMarkdown } from './text/markdown.ts';
