// Деньги — целые para, как в API и БД (1 RSD = 100 para). Валюта одна — RSD (ст. 34 ZDP).

export type Para = number;

export const CURRENCY = 'RSD';
export const PARA_PER_RSD = 100;

export function rsdToPara(rsd: number): Para {
  return Math.round(rsd * PARA_PER_RSD);
}

export function paraToRsd(para: Para): number {
  return para / PARA_PER_RSD;
}
