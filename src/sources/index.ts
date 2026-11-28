import { chinaIptvSources } from './china_iptv';
import { epgPwSources } from './epg_pw';
import { fanmingmingLiveSources } from './fanmingming_live';
import { hotelTvnSources } from './hotel_tvn';
// 恢复打开 iptvOrg 这两个绝对能跑的源
import { iptvOrgSources, iptvOrgStreamSources } from './iptv_org';
import { joevessIptvSources } from './joevess_iptv';
import { qwerttvvBjIptvSources } from './qwerttvv_bj_iptv';
import { yangM3uSources } from './yang_m3u';
import { youhunSources } from './youhun';
import { yuechanLiveSources } from './yuechan_live';
import { zbdsSources } from './zbds';
import type { TSources } from './utils';

export * from './china_iptv';
export * from './lan_proxy'; // 保持导出，供其他文件内部调用
export * from './utils';

export const sources: TSources = [
  // 优先把最稳定的源放在前面
  ...iptvOrgSources, 
  ...iptvOrgStreamSources,
  // 然后放入你原本想添加的其他源
  ...fanmingmingLiveSources,
  ...yuechanLiveSources,
  ...yangM3uSources,
  ...joevessIptvSources,
  ...hotelTvnSources,
  ...(process.env.SKIP_EPG === "1" ? [] : epgPwSources),
  ...qwerttvvBjIptvSources,
  ...chinaIptvSources,
  ...youhunSources,
  ...zbdsSources,
];