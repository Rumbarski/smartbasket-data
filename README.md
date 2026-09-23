# Smart Basket BG — цени от магазините

Ежедневна обработка на **отворените данни на КЗП „Колко струва“** (kolkostruva.bg):
цените на дребно и в промоция по търговски обекти на Lidl, Kaufland, Billa,
Fantastico, T Market и други вериги.

GitHub Actions пуска `pipeline/build.py` два пъти дневно. Резултатът се
публикува в клона **`data`**, откъдето приложението чете:

```
https://raw.githubusercontent.com/<потребител>/<хранилище>/data/v1/meta.json
```

## Какво има в `v1/`

| Файл | Съдържание |
| --- | --- |
| `meta.json` | дата на данните, вериги, категории, каталожни изделия (SKU) |
| `cities.json` | населени места с обекти (ЕКАТТЕ, координати, брой обекти по вериги) |
| `stores.json` | обектите: верига, адрес, координати (OSM или центъра на града) |
| `prices/<обект>.json` | днешните цени: `p` по продукти `[цена, редовна, промо, мин. 30 дни]` и `s` по каталожни изделия `[продукт, цена, цена за разфасовката, промо, приблизителна, мин. 30 дни]` |
| `products/<верига>.json` | имена, категории, разфасовки и медианна цена по веригата |
| `hist/<верига>/<0–31>.json` | история на цените по веригата (медиана по обектите), до 400 дни |
| `skuhist/<верига>.json` | история на каталожните изделия по веригата |

## Настройка (веднъж)

1. Създай **публично** хранилище в GitHub, например `smartbasket-data`.
2. Сложи работния процес на мястото му (файлът е тук като `prices-workflow.yml`,
   защото папката `.github` не се записва през връзката с компютъра):
   ```powershell
   New-Item -ItemType Directory -Force .github\workflows | Out-Null
   Move-Item -Force prices-workflow.yml .github\workflows\prices.yml
   ```
3. Качи съдържанието на тази папка (вече с папката `.github`).
4. Settings → Actions → General → Workflow permissions → **Read and write permissions** → Save.
5. Actions → „Цени от КЗП“ → **Run workflow**. Първото пускане тегли до 90 дни история
   и продължава 15–30 минути.
6. В приложението, във файла `.env`:
   `EXPO_PUBLIC_PRICES_URL=https://raw.githubusercontent.com/<потребител>/smartbasket-data/data`

## Локално

```bash
python -m unittest discover -s tests -t .
python -m pipeline.build --zips .cache/zips --prev prev --out site
```

Без външни зависимости — само стандартната библиотека на Python 3.11+.

## Източници и лицензи

- Цени: КЗП, портал „Колко струва“ — отворени данни (kolkostruva.bg/opendata).
- Населени места и координати (`data/ekatte.json`): „Places-in-Bulgaria“,
  © 2020 Linker Games EOOD, лиценз MIT.
- Местоположения на обектите: © участниците в OpenStreetMap, ODbL.

Показват се фактите от данните — без оценки за търговските практики.
