// Порт платформы (ADR-0012, ADR-0020 §13): экраны работают через него в Telegram, браузере и тестах.

export type PlatformKind = 'tma' | 'browser' | 'mock';
export type ColorScheme = 'light' | 'dark';
export type Unsubscribe = () => void;

export interface Insets {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

export interface LaunchInfo {
  /** Платформа клиента Telegram (ios, android, tdesktop, weba…) или `browser`. */
  platform: string;
  /** Версия Bot API клиента; в браузере — `0`. */
  version: string;
  /** Сырой initData для POST /auth/telegram; в браузере — `null`. */
  rawInitData: string | null;
  startParam: string | null;
  /** `language_code` пользователя Telegram. */
  languageCode: string | null;
}

export interface BottomButtonState {
  text: string;
  visible: boolean;
  enabled: boolean;
  loading: boolean;
  /** Цвета — из токенов design-tokens; без них — цвета темы Telegram. */
  color?: string;
  textColor?: string;
  shine?: boolean;
  /** Только SecondaryButton: где стоит относительно MainButton. */
  position?: 'left' | 'right' | 'top' | 'bottom';
}

export interface BottomButton {
  /** `false` — клиент не умеет нативную кнопку: приложение рисует её в контенте (`useBottomButtonState`). */
  readonly native: boolean;
  getState(): BottomButtonState;
  set(state: Partial<BottomButtonState>): void;
  subscribe(listener: () => void): Unsubscribe;
  onClick(listener: () => void): Unsubscribe;
  /** Нажатие кнопки, нарисованной в контенте. */
  click(): void;
}

export interface BackButton {
  readonly native: boolean;
  setVisible(visible: boolean): void;
  onClick(listener: () => void): Unsubscribe;
}

export interface PopupButton {
  id: string;
  type?: 'default' | 'ok' | 'close' | 'cancel' | 'destructive';
  text?: string;
}

export interface PopupParams {
  title?: string;
  message: string;
  buttons?: PopupButton[];
}

export type ImpactStyle = 'light' | 'medium' | 'heavy' | 'rigid' | 'soft';
export type NotificationType = 'error' | 'success' | 'warning';

export interface KeyValueStorage {
  get(key: string): Promise<string | null>;
  set(key: string, value: string): Promise<void>;
  remove(key: string): Promise<void>;
}

export interface Coordinates {
  latitude: number;
  longitude: number;
  accuracy?: number;
}

export type ShareResult = 'shared' | 'copied' | 'failed';

/** Что умеет текущий клиент; решает, нужен ли фолбэк. */
export interface Capabilities {
  secondaryButton: boolean;
  bottomBarColor: boolean;
  deviceStorage: boolean;
  cloudStorage: boolean;
  safeArea: boolean;
  location: boolean;
  shareMessage: boolean;
  requestContact: boolean;
  requestWriteAccess: boolean;
  verticalSwipes: boolean;
  closingConfirmation: boolean;
  haptics: boolean;
  popup: boolean;
}

export interface Platform {
  readonly kind: PlatformKind;
  readonly launch: LaunchInfo;
  readonly capabilities: Capabilities;
  isVersionAtLeast(version: string): boolean;

  ready(): void;
  expand(): void;
  close(): void;

  theme: {
    colorScheme(): ColorScheme;
    onChange(listener: (scheme: ColorScheme) => void): Unsubscribe;
    setHeaderColor(color: string): void;
    setBackgroundColor(color: string): void;
    setBottomBarColor(color: string): void;
  };
  viewport: {
    /** `viewportStableHeight`: высота без учёта анимаций клавиатуры и жестов. */
    stableHeight(): number;
    safeArea(): Insets;
    contentSafeArea(): Insets;
    onChange(listener: () => void): Unsubscribe;
  };

  backButton: BackButton;
  mainButton: BottomButton;
  secondaryButton: BottomButton;

  haptics: {
    impact(style: ImpactStyle): void;
    notification(type: NotificationType): void;
    selection(): void;
  };

  /** id нажатой кнопки или `null`, если попап закрыт без выбора. */
  popup(params: PopupParams): Promise<string | null>;
  confirm(message: string): Promise<boolean>;
  setClosingConfirmation(enabled: boolean): void;
  setVerticalSwipes(enabled: boolean): void;

  requestWriteAccess(): Promise<boolean>;
  requestContact(): Promise<boolean>;
  /** `savePreparedInlineMessage` на backend → id сюда. */
  shareMessage(preparedMessageId: string): Promise<boolean>;
  /** Ссылка на экран: в Telegram — выбор чата, в браузере — navigator.share или копирование. */
  shareLink(url: string, text?: string): Promise<ShareResult>;
  openLink(url: string): void;
  openTelegramLink(url: string): void;

  storage: {
    /** DeviceStorage (Bot API 9.0); раньше — CloudStorage, в браузере — localStorage. */
    device: KeyValueStorage;
    cloud: KeyValueStorage;
  };
  location: {
    request(): Promise<Coordinates | null>;
  };
}
