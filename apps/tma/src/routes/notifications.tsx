// S42 с разбором deep link уведомлений: `link` строки — тот же код, что у кнопки в боте, адрес
// экрана — по той же таблице, что при запуске (routes/startapp.ts). Фича маршруты не импортирует.
import { NotificationsScreen } from '../features/service/s42-notifications/index.ts';
import { startTarget } from './startapp.ts';

export function NotificationsRoute() {
  return <NotificationsScreen targetOf={startTarget} />;
}
