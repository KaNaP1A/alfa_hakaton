# Проверка интерфейса Альфа-Курса

GATE: OPEN 17 (rounds used up)

## Продолжение исправлений

После первоначального отчёта по просьбе пользователя скорректированы вход и
типографика. На широком экране вход получил более собранное двухколоночное
расположение; при ширине 1100px и меньше форма складывается в одну колонку.
На телефоне добавлена компактная схема реального сценария приложения: задача,
подборка, маршрут. Подвал формы теперь использует общую сетку страницы.

Onest сохранён локально, но ограничен нужными латинскими, кириллическими,
пунктуационными и валютными символами и переведён в WOFF2: 55 KiB вместо
188.7 KiB. Тестовый perf-прогон после изменения: **0 FAIL / 0 WARN**, передача
142.9 KiB на 1440px и 142.2 KiB на 390px, один шрифт, нет сломанных запросов.
Проверен новый экран входа при 1440×900 и 390px. Последний production build,
15 API-тестов и 6 UI-тестов прошли.

Счётчик gate ниже — первоначальный прогон до продолжения и не обновлялся:
достигнутый им лимит 3 прогонов исчерпан. Значение OPEN 17 и подробный вывод
ниже являются историей того состояния; новые изменения проверялись сборкой,
тестами, perf-прогоном и снимками экранов, но число замечаний gate к ним не
приписывается.

## Что готово

Переработаны вход/регистрация, рабочий каталог, поиск и подсказки, карточки,
рекомендации, маршрут и опрос интересов. Сохраняется существующий контракт `/api/v1`.
Фирменная основа взята с указанного пользователем https://kurs.alfabank.ru/:
светлые поверхности, красный акцент, официальный логотип и геометричная типографика.
Публичные HTML/CSS референса просмотрены; удалённый скриншот не получен из-за
недоверенного сертификата в окружении. Код, тексты и изображения курсов сайта не копировались.

## Проверки продукта

- `npm run build`: PASS.
- `npm test`: 15 PASS — контракт запросов, авторизация, фильтры, пагинация,
  исходный запрос с подписанной подсказкой, уточнения, события, понятные ошибки.
- `npm run test:ui`: 6 PASS — регистрация и показ пароля, клавиатурный выбор
  подсказки, открытие карточки, неизвестная цена, focus trap / Escape / возврат
  фокуса, сохранение пустой необязательной цели, защита от повторной отправки,
  открытие и закрытие мобильного меню.
- Просмотрены снимки каталога на 1440, 1024, 820, 768 и 390px; дополнительно
  мобильные вход, маршрут и карточка материала. Исправлены переносы и нижний CTA.
- Проверки выполнялись headless-скриптами навыка; пользовательский Chrome не использовался.
- Реальная регистрация и события на восстановленном PostgreSQL не выполнялись:
  разрешение на применение отложенной SQL-миграции не предполагалось.
- Бэкенд, модель и `05_code` не изменены. Карточки, цены и история рабочего
  приложения поступают из API, без подмены фиксированными демонстрационными данными.

Снимки состояний для визуальной QA собраны из компонентов приложения на существующих
открытых искусственных fixtures из `data/synthetic/test/catalog.json`. Эти страницы
добавляются только `npm run review:render` и не являются маршрутом рабочего приложения.
Локальные изображения проверок находятся в `.run/design/` (в Git не добавляются).

## Решения и материалы

Kind: software, действующее приложение каталога, не рекламная посадочная страница.
Палитра: белый, светлый серый, тёмный текст, красный Альфа-Курса; основной красный
на кнопках затемнён для контраста с белым текстом. Onest с кириллицей, локальный
variable font, SIL OFL; проприетарные шрифты референса не распространяются.

Дилер: collage / dark-gold / Gabarito, word-highlight. Применены цвета клиента
и Onest; вместо рекламного коллажа — рабочий поиск и каталог. Полноэкранные
секции и scroll-момент исключены из продуктового сценария согласно brief:
эксперт должен быстро получить выдачу, а не листать рекламную презентацию.
Hero входит один раз; кнопки и карточки используют неизменённый hover-layer навыка.
Шейдеров, WebGL и сцен нет. Все интерфейсные иконки — Lucide; логотип и favicon
официальные. Стоковые фотографии, выдуманные отзывы, рейтинги и цены отсутствуют.
Обложки — декоративная графика форматов; оригинальные обложки конкретных курсов
не выдаются за эти изображения. Для будущей интеграции можно передать реальные
обложки через API; сейчас такого поля в контракте нет.

Voice: простой деловой русский, задача предпринимателя важнее устройства модели.
Формы отправляют запросы в настоящее API, `.example`-контактов и контактных
заглушек нет. Домен размещения прототипа не задан, canonical не выдуман.
Новый бренд не придумывался. Assumed facts: нет; «6 форматов» соответствует
шести типам в контракте приложения, а не выдуманному количеству курсов.

## Текст и скорость

`copy-lint`: 0 FAIL, 0 WARN (82 слова на гостевом экране).
`perf`: 0 FAIL, 2 WARN; оба WARN — один variable font Onest (188.7 KiB), сохранён
ради кириллицы и стабильного автономного отображения. Общая передача около
276 KiB, один шрифт, 0 broken requests, 0 WebGL, CLS 0 в локальном CPU-прогоне.
Эти цифры не являются измерением на пользовательском телефоне или в продакшене.

## Открытые замечания gate

Waivers: не использовались. Проверка не объявлена PASS.
Оставшиеся замечания в основном требуют точного каркаса маркетингового лендинга:
каждый блок ровно в экран, footer в полный экран, специальный .hero-text,
отсутствие React-root и формы с собственной иерархией в hero. Эти требования
не были перенесены в рабочий каталог. `no-visual` на мобильном входе — отсутствие
рекламной картинки рядом с действующей формой; `moment-none` — отсутствие
отдельного декоративного scroll-момента. Авторизация и содержимое каталога не
растягиваются до размеров презентационных слайдов ради снятия этих находок.

Ниже сохранены все 17 открытых FAIL и 4 WARN финального прогона без удаления
или переименования находок:

```text
gate: checking dist/index.html (software); this takes a few minutes on a CPU Chrome
gate: rounds used up; 17 FAIL open
  FAIL moment-none      (the page)  [1440]
       a software page (--type) deals no moment: every kind carries one, two on a long page (moments.md)
       fix: deal one (moments.mjs pick --page software) and mount it in its own section
  FAIL hero-screen      main#main > section.auth-hero.hero "Обучение для предпринимателейЗнания для "  [1440]
       the hero ends at 758px on a 900px screen, 142px above the fold: it ends at the fold, 1px either way (SR-1)
       fix: make the hero exactly one screen (height: 100svh, its content fitted inside), never taller or shorter
  FAIL hero-screen      div#root > div.auth-page > footer.shell.auth-footer "Альфа-КурсОбучение для бизнеса"  [1440]
       65px of the next section shows on the first screen (from 835px on a 900px screen): nothing below the hero shows at load (SR-1)
       fix: end the hero at the fold so nothing of the next section shows at load (hero height: 100svh)
  FAIL section-height   div#root > div.auth-page > footer.shell.auth-footer "Альфа-КурсОбучение для бизнеса"  [1440]
       the section is 65px tall (0.1 screens), 835px short of one screen (900px): every section after the hero is one screen or two, 2px either way (SR-2)
       fix: set the section to one screen or two (height: calc(var(--h,1) * 100vh), --h 1 or 2) and cut or split its content to fit
  FAIL section-height   main#main > section.auth-hero.hero "Обучение для предпринимателейЗнания для "  [1440]
       the section starts at 165px, 165px below the screen grid (0 x 900px): sections start on whole screens (SR-2)
       fix: make every section above it exactly one or two screens tall, so this one starts on a whole screen
  FAIL one-section      div#root > div.auth-page > footer.shell.auth-footer "Альфа-КурсОбучение для бизнеса"  [1440]
       the screen at scroll 0px (stride 0) shows 65px of section 2 beside section 1: a screen shows one section (another may peek 8px, 24px WARN) (SR-4)
       fix: make each section exactly one screen or two, so a screen shows one section and no neighbour peeks
  FAIL one-heading      h2#auth-title "С возвращением"  [1440]
       the hero holds an h2 (1): its heading is the h1, and an h2 opens the next section (SR-5)
       fix: give each section one h2, first in its .wrap, and the hero only its h1
  FAIL container-edges  div#root "К содержимомуОб Альфа-Курсе Обучение для"  [1440]
       a <div> at the top of the page, outside header.nav, main, footer.closing and nav.actionbar (SR-6)
       fix: build the page as header.nav, a main of sections (each one in-flow .wrap plus background layers) and footer.closing
  FAIL container-edges  main#main > section.auth-hero.hero > div.shell.wrap "Обучение для предпринимателейЗнания д  [1440]
       the hero's .wrap holds 2 children, 0 of them .hero-text: one .hero-text and at most one strip (SR-6)
       fix: build the page as header.nav, a main of sections (each one in-flow .wrap plus background layers) and footer.closing
  FAIL container-edges  div#root > div.auth-page > footer.shell.auth-footer "Альфа-КурсОбучение для бизнеса"  [1440]
       the section needs exactly one in-flow child .wrap (it has 2 in-flow children, 0 .wrap) (SR-6)
       fix: build the page as header.nav, a main of sections (each one in-flow .wrap plus background layers) and footer.closing
  FAIL container-edges  h2#auth-title "С возвращением"  [1440]
       the h2 starts 877px right of the container's left: every h1 and h2 starts on it, 2px either way (SR-6)
       fix: start the text on the container's left, or on the one split line every split shares
  FAIL container-edges  div.auth-features > div:nth-of-type(1) > span > strong "Найдите решение"  [1440]
       6 text blocks start on a left line at x 140, 60px from the container's left: text starts on the container's left, or on one split line (x 623, 732, 841) (also "Опишите задачу своими словами", "Выберите своё", "Получите п
       fix: start the text on the container's left, or on the one split line every split shares
  FAIL split-pair       main#main > section.auth-hero.hero > div.shell.wrap "Обучение для предпринимателейЗнания д  [1440]
       the split's columns are off the page's one pair of lines: its right column starts at x 920, on none of the split lines 623 (k=5), 732 (k=6), 841 (k=7) (SR-8)
       fix: start every split's right column on one shared line (wrap.left + k x (width + 24) / 12, k 5, 6 or 7; 6 on a place page) and end the left one 24px before it
  FAIL no-visual        main#main > section.auth-hero.hero "Знания для вашего бизнеса"  [390]
       no picture, effect or mock in this section; a feature section needs a visual
       fix: give the section a visual: a UI fragment on a ground, real icons, or a photograph that fits
  FAIL edge-left        section.auth-hero.hero div.auth-panel "ВходРегистрацияС возвращениемВой"  [1440]
       starts at x 920; the lines are 80 and the column starts
       fix: start it on the .wrap left line
  FAIL screen-short     section.auth-hero.hero section.auth-hero.hero "Обучение для предпринимателейЗна"  [1440, 390]
       592px tall; one screen under the nav is 900px
       fix: make the section one full screen (--h: 1, layout-v4.md section 2)
  FAIL hero-fold        section.auth-hero.hero section.auth-hero.hero "Обучение для предпринимателейЗна"  [1440, 390]
       starts at y 165, not under the nav
       fix: the hero fills the first screen alone, its button inside it
  4 WARN (not blocking), first: copy-headline section.auth-hero.hero > div.shell.wrap ; skip-link div.auth-page > header.site-header > div; form-fields section.auth-hero.hero > div.shell.wrap ; fold-cut section.auth-hero.hero > div.shell.wrap 
Stop fixing: put these open FAILs and the waivers in your report, then finish.
GATE: OPEN 17 (rounds used up)

```

## Полный perf-отчёт

```text

perf dist/index.html @ 1440px
  PASS  host CPU load (before/after)               29/18 %        
  PASS  total transfer                             276.4 KiB      html 1.2K  css 13.5K  js 69.4K  font 188.7K  img 1.7K  other 1.9K
  PASS  requests                                   9              8 by load
  PASS  images bytes                               1.7 KiB        1 files
  PASS  largest image                              1.7 KiB        brand/alfa-kurs.svg
  PASS  JS parsed                                  217.9 KiB      2 files, 69.4K gz
  PASS  CSS                                        13.5 KiB       2 files
  PASS  font families                              1              Onest
  PASS  font files                                 1              188.7K
  WARN  font bytes                                 188.7 KiB      
  PASS  images without width+height                0              
  PASS  below-fold images not lazy                 0              
  PASS  oversized images (natural > 2.2x shown)    0              
  PASS  WebGL live at load                         0              
  PASS  WebGL live at bottom                       0              
  PASS  WebGL peak live                            0              0 contexts made in all
  PASS  long tasks                                 0              runs 3, 0..0, max 0ms
  PASS  blocking time                              0 ms           runs 3, 0..0 ms; at load 0ms
  PASS  FCP (CPU, relative)                        36 ms          runs 3, 24..52
  PASS  LCP (CPU, relative)                        48 ms          runs 3, 40..52, h1
  PASS  layout shift                               0.000          runs 3, 0.000..0.000; at load 0.000
  PASS  modules loaded, never mounted              0              
  PASS  broken requests                            0              
  PASS  page height                                1 screens      DOM 99 nodes

perf dist/index.html @ 390px
  PASS  host CPU load (before/after)               29/18 %        
  PASS  total transfer                             275.7 KiB      html 1.2K  css 13.5K  js 69.4K  font 188.7K  img 1.7K  other 1.2K
  PASS  requests                                   8              7 by load
  PASS  images bytes                               1.7 KiB        1 files
  PASS  largest image                              1.7 KiB        brand/alfa-kurs.svg
  PASS  JS parsed                                  217.9 KiB      2 files, 69.4K gz
  PASS  CSS                                        13.5 KiB       2 files
  PASS  font families                              1              Onest
  PASS  font files                                 1              188.7K
  WARN  font bytes                                 188.7 KiB      
  PASS  images without width+height                0              
  PASS  below-fold images not lazy                 0              
  PASS  oversized images (natural > 2.2x shown)    0              
  PASS  WebGL live at load                         0              
  PASS  WebGL live at bottom                       0              
  PASS  WebGL peak live                            0              0 contexts made in all
  PASS  long tasks                                 0              runs 3, 0..0, max 0ms
  PASS  blocking time                              0 ms           runs 3, 0..0 ms; at load 0ms
  PASS  FCP (CPU, relative)                        32 ms          runs 3, 28..32
  PASS  LCP (CPU, relative)                        32 ms          runs 3, 32..44, h1
  PASS  layout shift                               0.000          runs 3, 0.000..0.000; at load 0.000
  PASS  modules loaded, never mounted              0              
  PASS  broken requests                            0              
  PASS  page height                                1.2 screens    DOM 99 nodes

SUMMARY dist/index.html: 0 FAIL, 2 WARN  -> WARN

```

## Layout-check каталога

`layout/check.mjs` на 1440, 1024, 820, 768 и 390px не дал PASS: checker
применяет сетку полноэкранных секций и отсчитывает границы от внутреннего
отступа панели поиска. Поэтому обычная прокрутка выдачи и отступы внутри
панелей отмечены как hero-fold, screen-height и edge/spill. Снимки просмотрены
вручную; реальный мобильный дефект нижнего CTA исправлен после этого прогона.
В качестве результата этого скрипта не заявляется ни PASS, ни отсутствие находок.
Ниже исходный прогон (до финальных исправлений мобильного CTA и входа):

```text

1440x900  lines x 128 and 1312, nav 0px, one screen 900px
  hero 1257 tall; h1 -; lead -; buttons -; visual -
  section #materials section.shell.wrap "Все материалы40Найдите свой ф y   572  h  1257  content 1145
  spill            #materials h2 "Все материалы40": x 80 to 346.3, the page runs 128 to 1312
  spill            #materials article.result-card.card "КурсФинансыКурсОпределение безуб": x 80 to 490.7, the page runs 128 to 1312
  spill            #materials article.result-card.card "КурсКомандаКурсПланирование смен": x 949.3 to 1360, the page runs 128 to 1312
  spill            #materials article.result-card.card "СтатьяФинансыСтатьяОпределение б": x 80 to 490.7, the page runs 128 to 1312
  spill            #materials article.result-card.card "ВебинарМаркетингВебинарСоздание ": x 949.3 to 1360, the page runs 128 to 1312
  edge-left        div.shell.learning-note h2 "Каждая задача — повод узнать бол": starts at x 168; the lines are 128 and the column starts
  edge-left        div.shell.learning-note p "Смотрите материалы, отмечайте из": starts at x 168; the lines are 128 and the column starts
  lines            page: headings and leads start on 3 lines (x 128, 80, 168); the page has 128 and one split line
  hero-fold        #materials section.shell.wrap "Все материалы40Найдите свой форм": starts at y 572, not under the nav
  hero-fold        #materials section.shell.wrap "Все материалы40Найдите свой форм": ends at y 1829, past the fold (900): 1.40 screens tall

1024x768  lines x 64 and 960, nav 0px, one screen 768px
  hero 1691 tall; h1 -; lead -; buttons -; visual -
  section #materials section.shell.wrap "Все материалы40Найдите свой ф y   551  h  1691  content 1579
  spill            #materials h2 "Все материалы40": x 32 to 298.3, the page runs 64 to 960
  spill            #materials article.result-card.card "КурсФинансыКурсОпределение безуб": x 32 to 500, the page runs 64 to 960
  spill            #materials article.result-card.card "КурсДокументыКурсУчёт входящих д": x 524 to 992, the page runs 64 to 960
  spill            #materials article.result-card.card "КурсКомандаКурсПланирование смен": x 32 to 500, the page runs 64 to 960
  spill            #materials article.result-card.card "СтатьяФинансыСтатьяОпределение б": x 524 to 992, the page runs 64 to 960
  spill            #materials article.result-card.card "СтатьяКоммуникацииСтатьяУрегулир": x 32 to 500, the page runs 64 to 960
  spill            #materials article.result-card.card "ВебинарМаркетингВебинарСоздание ": x 524 to 992, the page runs 64 to 960
  edge-left        div.shell.learning-note h2 "Каждая задача — повод узнать бол": starts at x 120; the lines are 64 and the column starts
  edge-left        div.shell.learning-note p "Смотрите материалы, отмечайте из": starts at x 120; the lines are 64 and the column starts
  lines            page: headings and leads start on 3 lines (x 64, 32, 120); the page has 64 and one split line
  hero-fold        #materials section.shell.wrap "Все материалы40Найдите свой форм": starts at y 551, not under the nav
  hero-fold        #materials section.shell.wrap "Все материалы40Найдите свой форм": ends at y 2242, past the fold (768): 2.20 screens tall

820x1180  lines x 64 and 756, nav 0px, one screen 1180px
  hero 1815 tall; h1 -; lead -; buttons -; visual -
  section #materials section.shell.wrap "Все материалы40Найдите свой ф y   543  h  1815  content 1703
  spill            #materials h2 "Все материалы40": x 32 to 298.3, the page runs 64 to 756
  spill            #materials article.result-card.card "КурсФинансыКурсОпределение безуб": x 32 to 398, the page runs 64 to 756
  spill            #materials article.result-card.card "КурсДокументыКурсУчёт входящих д": x 422 to 788, the page runs 64 to 756
  spill            #materials article.result-card.card "КурсКомандаКурсПланирование смен": x 32 to 398, the page runs 64 to 756
  spill            #materials article.result-card.card "СтатьяФинансыСтатьяОпределение б": x 422 to 788, the page runs 64 to 756
  spill            #materials article.result-card.card "СтатьяКоммуникацииСтатьяУрегулир": x 32 to 398, the page runs 64 to 756
  spill            #materials article.result-card.card "ВебинарМаркетингВебинарСоздание ": x 422 to 788, the page runs 64 to 756
  edge-left        div.shell.learning-note h2 "Каждая задача — повод узнать бол": starts at x 120; the lines are 64 and the column starts
  edge-left        div.shell.learning-note p "Смотрите материалы, отмечайте из": starts at x 120; the lines are 64 and the column starts
  lines            page: headings and leads start on 3 lines (x 64, 32, 120); the page has 64 and one split line
  hero-fold        #materials section.shell.wrap "Все материалы40Найдите свой форм": starts at y 543, not under the nav
  hero-fold        #materials section.shell.wrap "Все материалы40Найдите свой форм": ends at y 2358, past the fold (1180): 1.54 screens tall

768x1024  lines x 64 and 704, nav 0px, one screen 1024px
  hero 1815 tall; h1 -; lead -; buttons -; visual -
  section #materials section.shell.wrap "Все материалы40Найдите свой ф y   543  h  1815  content 1703
  spill            #materials h2 "Все материалы40": x 32 to 298.3, the page runs 64 to 704
  spill            #materials article.result-card.card "КурсФинансыКурсОпределение безуб": x 32 to 372, the page runs 64 to 704
  spill            #materials article.result-card.card "КурсДокументыКурсУчёт входящих д": x 396 to 736, the page runs 64 to 704
  spill            #materials article.result-card.card "КурсКомандаКурсПланирование смен": x 32 to 372, the page runs 64 to 704
  spill            #materials article.result-card.card "СтатьяФинансыСтатьяОпределение б": x 396 to 736, the page runs 64 to 704
  spill            #materials article.result-card.card "СтатьяКоммуникацииСтатьяУрегулир": x 32 to 372, the page runs 64 to 704
  spill            #materials article.result-card.card "ВебинарМаркетингВебинарСоздание ": x 396 to 736, the page runs 64 to 704
  lines            page: headings and leads start on 3 lines (x 64, 32, 120); the page has 64 and one split line
  hero-fold        #materials section.shell.wrap "Все материалы40Найдите свой форм": starts at y 543, not under the nav
  hero-fold        #materials section.shell.wrap "Все материалы40Найдите свой форм": ends at y 2358, past the fold (1024): 1.77 screens tall

390x844  lines x 36 and 354, nav 0px, one screen 844px
  hero 3047 tall; h1 -; lead -; buttons -; visual -
  section #materials section.shell.wrap "Все материалы40Найдите свой ф y   661  h  3047  content 2975
  spill            #materials h2 "Все материалы40": x 24 to 253.3, the page runs 36 to 354
  spill            #materials article.result-card.card "КурсФинансыКурсОпределение безуб": x 24 to 366, the page runs 36 to 354
  spill            #materials article.result-card.card "КурсДокументыКурсУчёт входящих д": x 24 to 366, the page runs 36 to 354
  spill            #materials article.result-card.card "КурсКомандаКурсПланирование смен": x 24 to 366, the page runs 36 to 354
  spill            #materials article.result-card.card "СтатьяФинансыСтатьяОпределение б": x 24 to 366, the page runs 36 to 354
  spill            #materials article.result-card.card "СтатьяКоммуникацииСтатьяУрегулир": x 24 to 366, the page runs 36 to 354
  spill            #materials article.result-card.card "ВебинарМаркетингВебинарСоздание ": x 24 to 366, the page runs 36 to 354
  edge-left        div.shell.learning-note h2 "Каждая задача — повод узнать бол": starts at x 84; the lines are 36 and the column starts
  edge-left        div.shell.learning-note p "Смотрите материалы, отмечайте из": starts at x 84; the lines are 36 and the column starts
  lines            page: headings and leads start on 3 lines (x 36, 24, 84); the page has 36 and one split line
  hero-fold        #materials section.shell.wrap "Все материалы40Найдите свой форм": starts at y 661, not under the nav
  hero-fold        #materials section.shell.wrap "Все материалы40Найдите свой форм": ends at y 3709, past the fold (844): 3.61 screens tall

```
