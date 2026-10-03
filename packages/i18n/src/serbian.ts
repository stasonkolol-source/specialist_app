// Сербские каталоги (кириллица) — отдельный чанк: в первый экран попадает только русский, общий
// неймспейс сербского и транслитерация. sr-Latn считается из них при загрузке (resources.ts).
import srCyrlAccount from './catalogs/sr-Cyrl/account.json' with { type: 'json' };
import srCyrlCatalog from './catalogs/sr-Cyrl/catalog.json' with { type: 'json' };
import srCyrlCommon from './catalogs/sr-Cyrl/common.json' with { type: 'json' };
import srCyrlJobs from './catalogs/sr-Cyrl/jobs.json' with { type: 'json' };
import srCyrlMessages from './catalogs/sr-Cyrl/messages.json' with { type: 'json' };
import srCyrlOnboarding from './catalogs/sr-Cyrl/onboarding.json' with { type: 'json' };
import srCyrlSafety from './catalogs/sr-Cyrl/safety.json' with { type: 'json' };
import srCyrlService from './catalogs/sr-Cyrl/service.json' with { type: 'json' };
import srCyrlSpecialist from './catalogs/sr-Cyrl/specialist.json' with { type: 'json' };
import type { Messages } from './resources.ts';

export const SR_CYRL: Messages = {
  common: srCyrlCommon,
  service: srCyrlService,
  onboarding: srCyrlOnboarding,
  specialist: srCyrlSpecialist,
  catalog: srCyrlCatalog,
  jobs: srCyrlJobs,
  messages: srCyrlMessages,
  account: srCyrlAccount,
  safety: srCyrlSafety,
};
