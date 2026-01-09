"""
Текст инструкции для команды /help.
"""

HELP_TEXT = """📖 <b>Инструкция по работе с ботом</b>

<b>🎯 Цель бота:</b>
Бот автоматически поддерживает лимитные ордера, не давая им исполниться. Когда текущая цена приближается к цене ордера, бот автоматически переставляет ордер на безопасное расстояние.

⚠️ <b>ВАЖНО: Перед использованием бота</b>
Перед регистрацией в боте необходимо <b>совершить хотя бы одну сделку через веб-интерфейс</b> на <a href="https://predict.fun?ref=73581">predict.fun</a>. Это необходимо для установки approvals (разрешений) для токенов в вашем кошельке. Без этого бот не сможет размещать ордера.

<b>🔐 Регистрация (/start):</b>
При регистрации вам понадобятся три параметра от одного и того же кошелька:

1. <b>Адрес кошелька (Deposit Address)</b>
   📍 Где взять: Страница Portfolio на <a href="https://predict.fun/">predict.fun</a>
   🔗 Ссылка: <a href="https://predict.fun/">https://predict.fun/</a>
   💡 Это адрес вашего Predict Account (смарт-кошелька)

2. <b>Приватный ключ (Privy Wallet Private Key)</b>
   📍 Где взять: Страница настроек аккаунта (Account Settings)
   🔗 Ссылка: <a href="https://predict.fun/account/settings?ref=73581">https://predict.fun/account/settings</a>
   💡 Это приватный ключ от Privy Wallet, который владеет вашим Predict Account

3. <b>API ключ</b>
   📍 Где взять: Откройте тикет в Discord сервере predict.fun
   🔗 Ссылка: <a href="https://discord.gg/predictdotfun">https://discord.gg/predictdotfun</a>
   💡 Запросите API ключ для вашего кошелька через Discord

⚠️ <b>Критически важно:</b> Все три параметра должны относиться к <b>одному и тому же кошельку</b>. API ключ от другого кошелька не позволит размещать ордера.

<b>📊 Размещение ордера (/make_market):</b>
1. Введите ссылку на маркет <a href="https://predict.fun?ref=73581">predict.fun</a>
2. Если маркет категориальный — выберите подмаркет
3. Введите сумму в USDT (например: 10)
4. Выберите сторону: ✅ YES или ❌ NO
5. Укажите смещение цены в центах (например: 0.1)
   Это расстояние от лучшей цены покупки (best bid), на котором будет размещен ордер
6. Выберите направление: 📈 BUY или 📉 SELL
   (SELL можно использовать для продажи shares)
7. Укажите порог изменения цены в центах (например: 0.5)
   Это минимальное изменение цены, при котором бот переставит ордер

<b>Пример:</b>
Маркет: "Будет ли дождь завтра?"
Сумма: 10 USDT
Сторона: YES
Смещение: 0.1 цента
Направление: BUY
Порог изменения: 0.5 цента

Ордер будет размещен на 0.1 цента ниже текущей лучшей цены покупки. Бот будет автоматически переставлять ордер, когда цена изменится на 0.5 цента или более.

<b>📋 Просмотр ордеров (/orders):</b>
Команда позволяет:
• Просмотреть все ваши ордера
• Отменить ордер
• Найти ордер по ID или названию маркета

⚠️ <b>Важно:</b> Управлять можно только ордерами, которые были созданы через бота. Ордера, размещенные вручную на платформе, не отображаются.

📬 При исполнении ордера бот автоматически отправит вам уведомление с деталями исполнения.

<b>💬 Поддержка:</b>
По всем вопросам обращайтесь через команду /support"""

HELP_TEXT_ENG = """📖 <b>Bot Usage Instructions</b>

<b>🎯 Bot Purpose:</b>
The bot automatically maintains limit orders, preventing them from being executed. When the current price approaches the order price, the bot automatically repositions the order to a safe distance.

⚠️ <b>IMPORTANT: Before Using the Bot</b>
Before registering in the bot, you must <b>complete at least one trade through the web interface</b> on <a href="https://predict.fun?ref=73581">predict.fun</a>. This is necessary to set up approvals (permissions) for tokens in your wallet. Without this, the bot will not be able to place orders.

<b>🔐 Registration (/start):</b>
When registering, you will need three parameters from the same wallet:

1. <b>Wallet Address (Deposit Address)</b>
   📍 Where to find: Portfolio page on <a href="https://predict.fun?ref=73581">predict.fun</a>
   🔗 Link: <a href="https://predict.fun?ref=73581">https://predict.fun</a>
   💡 This is your Predict Account (smart wallet) address

2. <b>Private Key (Privy Wallet Private Key)</b>
   📍 Where to find: Account Settings page
   🔗 Link: <a href="https://predict.fun/account/settings?ref=73581">https://predict.fun/account/settings</a>
   💡 This is the private key of the Privy Wallet that owns your Predict Account

3. <b>API Key</b>
   📍 Where to find: Open a ticket in the predict.fun Discord server
   🔗 Link: <a href="https://discord.gg/predictdotfun">https://discord.gg/predictdotfun</a>
   💡 Request an API key for your wallet through Discord

⚠️ <b>Critical:</b> All three parameters must belong to the <b>same wallet</b>. An API key from another wallet will not allow placing orders.

<b>📊 Placing an Order (/make_market):</b>
1. Enter the <a href="https://predict.fun?ref=73581">predict.fun</a> market link
2. If the market is categorical — select a submarket
3. Enter the amount in USDT (e.g., 10)
4. Select side: ✅ YES or ❌ NO
5. Specify price offset in cents (e.g., 0.1)
   This is the distance from the best bid price where the order will be placed
6. Select direction: 📈 BUY or 📉 SELL
   (SELL can be used to sell shares)
7. Specify price change threshold in cents (e.g., 0.5)
   This is the minimum price change at which the bot will reposition the order

<b>Example:</b>
Market: "Will it rain tomorrow?"
Amount: 10 USDT
Side: YES
Offset: 0.1 cents
Direction: BUY
Change threshold: 0.5 cents

The order will be placed 0.1 cents below the current best bid price. The bot will automatically reposition the order when the price changes by 0.5 cents or more.

<b>📋 Viewing Orders (/orders):</b>
The command allows you to:
• View all your orders
• Cancel an order
• Find an order by ID or market name

⚠️ <b>Important:</b> You can only manage orders that were created through the bot. Orders placed manually on the platform are not displayed.

📬 When an order is executed, the bot will automatically send you a notification with execution details.

<b>💬 Support:</b>
For all questions, contact us via the /support command"""

HELP_TEXT_CN = """📖 <b>机器人使用说明</b>

<b>🎯 机器人目的:</b>
机器人自动维护限价订单，防止订单被执行。当当前价格接近订单价格时，机器人会自动将订单重新定位到安全距离。

⚠️ <b>重要：使用机器人之前</b>
在机器人中注册之前，您必须通过 <a href="https://predict.fun?ref=73581">predict.fun</a> 的网页界面<b>完成至少一笔交易</b>。这对于在您的钱包中设置approvals（权限）是必要的。没有这个，机器人将无法下订单。

<b>🔐 注册 (/start):</b>
注册时，您需要来自同一钱包的三个参数：

1. <b>钱包地址（存款地址）</b>
   📍 在哪里找到：<a href="https://predict.fun?ref=73581">predict.fun</a> 上的投资组合页面
   🔗 链接：<a href="https://predict.fun?ref=73581">https://predict.fun</a>
   💡 这是您的Predict Account（智能钱包）地址

2. <b>私钥（Privy钱包私钥）</b>
   📍 在哪里找到：账户设置页面
   🔗 链接：<a href="https://predict.fun/account/settings?ref=73581">https://predict.fun/account/settings</a>
   💡 这是拥有您的Predict Account的Privy钱包的私钥

3. <b>API密钥</b>
   📍 在哪里找到：在predict.fun Discord服务器中打开工单
   🔗 链接：<a href="https://discord.gg/predictdotfun">https://discord.gg/predictdotfun</a>
   💡 通过Discord为您的钱包请求API密钥

⚠️ <b>关键：</b> 所有三个参数必须属于<b>同一个钱包</b>。来自其他钱包的API密钥将无法下订单。

<b>📊 下订单 (/make_market):</b>
1. 输入 <a href="https://predict.fun?ref=73581">predict.fun</a> 市场链接
2. 如果市场是分类市场 — 选择子市场
3. 输入USDT金额（例如：10）
4. 选择方向：✅ YES 或 ❌ NO
5. 指定价格偏移（以美分计，例如：0.1）
   这是订单将放置的最佳买入价（best bid）的距离
6. 选择方向：📈 BUY 或 📉 SELL
   （SELL可用于出售shares）
7. 指定价格变化阈值（以美分计，例如：0.5）
   这是机器人将重新定位订单的最小价格变化

<b>示例:</b>
市场："明天会下雨吗？"
金额：10 USDT
方向：YES
偏移：0.1美分
方向：BUY
变化阈值：0.5美分

订单将放置在当前最佳买入价下方0.1美分处。当价格变化0.5美分或更多时，机器人将自动重新定位订单。

<b>📋 查看订单 (/orders):</b>
该命令允许您：
• 查看所有订单
• 取消订单
• 通过ID或市场名称查找订单

⚠️ <b>重要:</b> 您只能管理通过机器人创建的订单。在平台上手动放置的订单不会显示。

📬 当订单被执行时，机器人会自动向您发送包含执行详情的通知。

<b>💬 支持:</b>
如有任何问题，请通过 /support 命令联系我们"""

