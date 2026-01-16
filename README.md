# predict.fun Market Making Bot

A Telegram bot for placing limit orders on [predict.fun](https://predict.fun/) prediction markets. The bot provides an intuitive interface for market making strategies with secure credential management, invite-based access control, and automatic order synchronization.

## Features

### 🔐 Secure Registration with Invite System
- **⚠️ Important Prerequisite**: Before registration, you must complete at least one trade through the web interface on [predict.fun](https://predict.fun/) to set up token approvals in your wallet
- **Invite-Based Access**: Registration requires a valid invite code (10-character alphanumeric)
- **Encrypted Storage**: All sensitive data (wallet address, private key, API key) is encrypted using AES-GCM encryption
- **Async SQLite Database**: User credentials are stored locally in an encrypted SQLite database using `aiosqlite` for non-blocking operations
- **Zero Trust**: Your private keys never leave your server in unencrypted form
- **Atomic Invite Usage**: Invites are used atomically at the end of registration to prevent conflicts
- **Data Validation**: 
  - Wallet address, private key, and API key must be unique
  - Input trimming (removes leading/trailing whitespace)
  - Important notes during registration about matching wallet, private key, and API key
- **Connection Testing**: API connection is tested at the end of registration using `get_my_orders` before saving user data
- **Error Handling**: User-friendly error messages with error codes and timestamps for support reference
- **Visual Guides**: Step-by-step registration with screenshots showing where to find wallet address, private key, and API key

### 🎫 Invite Management (Admin Only)
- **Invite Generation**: Admin command `/get_invites [count]` generates and displays unused invite codes (default: 10)
- **Automatic Creation**: System automatically creates new invites if fewer than requested are available
- **Statistics**: View total, used, and unused invite counts
- **One-Time Use**: Each invite can only be used once
- **Unique Codes**: 10-character alphanumeric codes with uniqueness validation

### 👤 User Management (Admin Only)
- **User Deletion**: Admin command `/delete_user` allows removing users from the database
- **Complete Removal**: Deletes user, all their orders, and clears associated invites
- **Re-registration Support**: Deleted users can register again with a new invite code
- **Database Statistics**: Admin command `/stats` provides comprehensive database statistics including user counts, order statistics by status, and invite statistics
- **Database Export**: Admin command `/get_db` exports all database tables to CSV files in a ZIP archive, plus log files

### 📊 Market Order Placement
- **Interactive Flow**: Step-by-step process for placing limit orders
- **Market Analysis**: View market information including:
  - Best bid/ask prices for YES and NO tokens
  - Spread and liquidity metrics
  - Top 5 bids and asks with price visualization in cents
- **Smart Validation**: Automatic balance checks and price validation
- **Categorical Markets**: Support for multi-outcome markets with submarket selection
- **Reposition Threshold**: Configurable threshold (in cents) for when orders should be repositioned
- **Error Handling**: Clear error messages when API calls fail

### 💰 Order Management
- **Order List**: View all your orders with pagination (`/orders` command)
- **Order Search**: Search orders by order ID, market ID, market title, token name, or side
- **Order Cancellation**: Cancel orders directly from the bot interface with detailed error messages
- **Price Offset in Cents**: Set order prices relative to best bid using intuitive cent-based offsets
- **Direction Selection**: Choose BUY (below current price) or SELL (above current price, can be used to sell shares)
- **Order Confirmation**: Review all settings before placing orders
- **Order Status Tracking**: View order status (OPEN, FILLED, CANCELLED, EXPIRED, INVALIDATED) aligned with API statuses
- **Bot-Only Orders**: Only orders created through the bot can be managed; manually placed orders are not displayed
- **Execution Notifications**: Automatic notifications when orders are executed with execution details

### 🔄 Automatic Order Synchronization
- **Background Task**: Automatically synchronizes orders every 60 seconds
- **Order Status Monitoring**: Checks order status via API before processing
  - Automatically updates database when orders are filled, cancelled, expired, or invalidated externally
  - Sends notifications for filled orders with order details (price, market link)
  - Silently updates cancelled/expired/invalidated orders without notifications
- **Price Tracking**: Monitors market price changes and maintains constant offset from current price
- **Smart Updates**: Only moves orders when price change exceeds configurable threshold (default 0.5 cents)
- **Batch Operations**: Efficiently cancels and places orders in batches per user
- **User Notifications**: Sends notifications about:
  - Price changes (before repositioning)
  - Order updates (after successful repositioning)
  - Order filled (when order is executed)
  - Placement errors (with detailed error messages)
- **Non-blocking**: All operations are asynchronous and don't block the bot's event loop
- **Safety Checks**: Only places new orders after successfully canceling old ones

### 📝 Logging & Monitoring
- **Separate Log Files**: Different log files for different modules:
  - `logs/bot.log` - Main bot operations (INFO level and above)
  - `logs/sync_orders.log` - Order synchronization operations
- **Dual-Level Logging**: 
  - File logs: INFO+ with detailed format including `filename:lineno` for debugging
  - Console logs: WARNING+ with simplified format for important messages only
- **Detailed Logging**: Comprehensive logging with user IDs, market IDs, and execution times
- **Performance Monitoring**: Logs start time, end time, and duration for each user's processing
- **Error Tracking**: Full traceback logging for debugging

### 💬 Support System
- **User Support**: Command `/support` allows users to contact the administrator
- **Message Forwarding**: Support messages (text or photo with caption) are forwarded to the admin
- **User Information**: Admin receives user ID, username, and name with each support message
- **No Registration Required**: Support command is available to all users (no registration needed)
- **Confirmation**: Users receive confirmation when their message is sent

### 📖 Help & Documentation
- **Multi-Language Help**: Command `/help` provides comprehensive instructions in three languages:
  - 🇬🇧 English (default)
  - 🇷🇺 Russian
  - 🇨🇳 Chinese
- **Interactive Language Selection**: Inline buttons for easy language switching
- **Complete Guide**: Includes registration instructions, order placement workflow, order management, and support information

### 💼 Account Management
- **Account Information**: Command `/check_account` displays:
  - USDT balance (from blockchain)
  - Number of open orders
  - Number of open positions
  - Total value in positions (in USDT)
  - Proxy status (if configured)
- **Referral Code**: Command `/set_ref_code` allows setting a 5-character referral code (one-time setup)

### 🔐 Proxy Management
- **Proxy Configuration**: Proxy is required during registration and can be updated later via `/set_proxy` command
- **Format Validation**: Proxy format is validated (ip:port:login:password)
- **Health Checking**: Proxy connection is tested before saving using HTTP requests
- **Status Tracking**: Proxy status is tracked (working/failed/unknown) in the database
- **Background Monitoring**: Automatic proxy health checks every 5 minutes for all users
- **Status Notifications**: Users receive notifications when proxy status changes:
  - ⚠️ Notification when proxy stops working (working → failed)
  - ✅ Notification when proxy is restored (failed → working)
- **API Integration**: All API requests use configured proxy if available
- **Account Display**: Proxy status is shown in `/check_account` command with visual indicators
- **Automatic Updates**: Proxy status is automatically updated during health checks

### 🛡️ Security & Performance
- **Anti-Spam Protection**: Built-in middleware to prevent message spam
- **Async Architecture**: Fully asynchronous codebase using `aiosqlite` and `asyncio`
- **Non-blocking I/O**: All database and API operations are non-blocking
- **Modular Design**: Clean separation of concerns with routers and modules
- **Registration Check**: Commands verify user registration before execution

## Getting Started

### Prerequisites

- Python 3.13+
- Telegram Bot Token (from [@BotFather](https://t.me/botfather))
- Predict.fun API Key (obtain by opening a ticket in [Discord](https://discord.gg/predictdotfun))
- BNB Chain RPC URL
- Wallet address (Deposit Address from Portfolio page on [predict.fun](https://predict.fun/))
- Private key (Privy Wallet Private Key from [Account Settings](https://predict.fun/account/settings))
- Admin Telegram ID (for invite management)
- ⚠️ **Important**: Complete at least one trade through the web interface before using the bot

### Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd predict_fun
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file in the project root:
```env
BOT_TOKEN=your_telegram_bot_token
MASTER_KEY=your_32_byte_hex_encryption_key
RPC_URL=your_bnb_chain_rpc_url
ADMIN_TELEGRAM_ID=your_telegram_user_id
```

4. Generate a master key for encryption:
```python
import secrets
print(secrets.token_hex(32))
```

5. Run the bot:
```bash
cd bot
python main.py
```

### Docker Deployment

The project includes Docker support for easy deployment:

1. Build and run with Docker Compose:
```bash
docker-compose up -d
```

2. View logs:
```bash
docker-compose logs -f bot
```

3. Stop the bot:
```bash
docker-compose down
```

For detailed deployment instructions, see [DEPLOY.md](DEPLOY.md).

**Important**: 
- The `.env` file must be present in the project root
- Database and logs are persisted via Docker volumes
- Make sure to set up proper file permissions for the `logs/` directory

## Usage

### ⚠️ Prerequisites

**Before registering in the bot**, you must:
1. Complete at least one trade through the web interface on [predict.fun](https://predict.fun/)
2. This is necessary to set up token approvals (permissions) in your wallet
3. Without this, the bot will not be able to place orders

### Registration

1. Start the bot with `/start`
2. Enter your invite code (10-character alphanumeric code)
3. Enter your **Wallet Address (Deposit Address)**
   - 📍 **Where to find**: Portfolio page on [predict.fun](https://predict.fun/)
   - 💡 This is your Predict Account (smart wallet) address
   - ⚠️ **Important**: Must be the wallet address for which the API key was obtained
4. Enter your **Private Key (Privy Wallet Private Key)**
   - 📍 **Where to find**: [Account Settings page](https://predict.fun/account/settings)
   - 💡 This is the private key of the Privy Wallet that owns your Predict Account
   - ⚠️ **Important**: Must correspond to the wallet address from step 3
5. Enter your **API Key**
   - 📍 **Where to find**: Open a ticket in the [predict.fun Discord server](https://discord.gg/predictdotfun)
   - 💡 Request an API key for your wallet through Discord
   - ⚠️ **Important**: Must be the API key obtained for the wallet from step 3
6. Enter your **Proxy Server**
   - Format: `ip:port:login:password`
   - Example: `192.168.1.1:8080:user:pass`
   - Proxy connection is tested before saving
   - Can be updated later using `/set_proxy` command

⚠️ **Critical**: All three parameters (wallet address, private key, API key) must belong to the **same wallet**. An API key from another wallet will not allow placing orders.

All data is encrypted and stored securely. The bot validates:
- Uniqueness of wallet address, private key, and API key
- API connection at the end of registration (using `get_my_orders`)
- If connection test fails, registration is aborted and you'll need to restart with `/start`

The invite code is validated and used atomically at the end of registration only if all checks pass.

### Invite Management (Admin Only)

1. Use `/get_invites [count]` to get unused invite codes (default: 10)
   - Example: `/get_invites 5` to get 5 invite codes
2. The system automatically creates new invites if needed
3. View statistics: total, used, and unused invite counts
4. Share invite codes with users who need access

### Placing Orders

1. Use `/make_market` to start the order placement flow
2. Enter a market URL from [predict.fun](https://predict.fun/)
3. For categorical markets, select a submarket
4. Review market information (spread, liquidity, best bids/asks)
5. Enter the farming amount in USDT
6. Select side (YES or NO)
7. View top 5 bids and asks
8. Set price offset in cents relative to best bid
9. Choose direction (BUY or SELL)
10. Set reposition threshold (minimum price change in cents to trigger repositioning, default 0.5)
11. Confirm and place the order

### Managing Orders

1. Use `/orders` to view all your orders
2. Browse orders with pagination (10 orders per page)
3. Use the search function to find specific orders
4. Cancel orders by entering the order ID (order list remains visible for easy copying)
5. View order details: status (OPEN/FILLED/CANCELLED/EXPIRED/INVALIDATED), price, amount, market, creation date

⚠️ **Note**: You can only manage orders that were created through the bot. Orders placed manually on the platform are not displayed.

📬 **Notifications**: When an order is executed, the bot automatically sends you a notification with execution details (price, market link, etc.).

### Getting Help

1. Use `/help` to view comprehensive bot instructions
2. Select your preferred language (English, Russian, or Chinese) using inline buttons
3. The help includes:
   - Bot purpose and functionality
   - Registration instructions with important notes
   - Step-by-step order placement guide with examples
   - Order management information
   - Support contact information

### Contacting Support

1. Use `/support` to contact the administrator
2. Enter your question or describe the issue
3. You can send text or a photo with a caption
4. Your message will be forwarded to the administrator with your user information (ID, username, name)
5. You'll receive a confirmation when your message is sent

### Checking Account Information

1. Use `/check_account` to view your account statistics
2. The bot displays:
   - Current USDT balance (from blockchain)
   - Number of open orders
   - Number of open positions
   - Total value locked in positions

### Setting Referral Code

1. Use `/set_ref_code` to set your referral code
2. Enter a 5-character referral code
3. ⚠️ **Important**: The code can only be set once and cannot be changed later
4. The referral code must be exactly 5 characters long

### Proxy Management

1. Use `/set_proxy` to configure or update your proxy server
2. Enter proxy in format: `ip:port:login:password`
   - Example: `192.168.1.1:8080:user:pass`
3. The bot validates the format and tests the connection
4. Proxy status is automatically monitored every 5 minutes
5. You'll receive notifications if proxy status changes (working ↔ failed)
6. View proxy status in `/check_account` command
7. ⚠️ **Note**: Proxy is required for secure connections to the Predict.fun API

## Project Structure

```
bot/
├── main.py                  # Main bot entry point, background tasks, user commands
├── config.py                # Configuration and settings management
├── database.py              # Async database operations (aiosqlite)
├── aes.py                   # AES-GCM encryption utilities
├── spam_protection.py       # Anti-spam middleware
├── logger_config.py         # Logging configuration and setup
├── help_text.py             # Multi-language help text (English, Russian, Chinese)
├── start_router.py          # User registration flow (/start command)
├── market_router.py         # Market order placement flow (/make_market command)
├── orders_dialog.py         # Order management dialog (/orders command)
├── sync_orders.py           # Automatic order synchronization background task
├── invites.py               # Invite management functions
├── admin.py                 # Admin commands router (/get_db, /get_invites, /stats, /delete_user)
├── referral_router.py       # Referral code management (/set_ref_code command)
├── proxy_router.py          # Proxy management router (/set_proxy command)
├── proxy_checker.py         # Proxy validation and health checking
├── predict_api/             # Predict.fun API client implementation
│   ├── __init__.py          # Module exports
│   ├── client.py            # REST API client (PredictAPIClient)
│   ├── sdk_operations.py    # SDK operations (balance, signing, cancellation)
│   ├── auth.py              # JWT authentication
│   └── README.md            # API client documentation
└── users.db                 # SQLite database (created automatically)

tests/                        # Test suite
├── conftest.py              # Pytest configuration and fixtures
├── test_predict_api_client.py  # Tests for API client
├── test_sdk_operations.py   # Tests for SDK operations
└── test_sync_orders.py     # Tests for order synchronization

files/                        # Static files (images for registration guides)
├── addr.png                 # Wallet address screenshot
├── api.png                  # API key screenshot
└── private.png              # Private key screenshot
```

## Architecture

The bot uses a modular router-based architecture:

- **Routers**: Separate routers for different features:
  - `start_router` - User registration
  - `market_router` - Order placement
  - `referral_router` - Referral code management
  - `proxy_router` - Proxy management
  - `admin_router` - Admin commands
  - Main router in `main.py` - User commands (orders, help, support, check_account)
- **Async Database**: All database operations use `aiosqlite` for non-blocking I/O
- **Background Tasks**: 
  - Order synchronization runs every 60 seconds
  - Proxy health checking runs every 5 minutes
- **Dialogs**: Complex multi-step interactions use `aiogram-dialog` for better UX
- **Middleware**: Global anti-spam protection for all messages and callbacks
- **API Client**: Uses `PredictAPIClient` (REST API) and `predict_sdk.OrderBuilder` (SDK) for all API operations
- **Proxy Support**: Optional proxy configuration for secure API connections

## Security

- **AES-GCM Encryption**: Industry-standard encryption for sensitive data
- **Local Storage**: All data stored locally on your server
- **No Third-Party Sharing**: Your credentials are never shared with third parties
- **Encrypted Database**: SQLite database contains only encrypted data
- **Async Operations**: Non-blocking I/O prevents performance issues
- **Invite System**: Access control through invite codes

## Configuration

The bot supports the following environment variables:

- `BOT_TOKEN`: Telegram bot token (required)
- `MASTER_KEY`: 32-byte hex key for encryption (required)
- `RPC_URL`: BNB Chain RPC endpoint (required)
- `ADMIN_TELEGRAM_ID`: Telegram user ID for admin commands (required for invite management)

## Commands

### User Commands
- `/start` - Register and set up your account (requires invite code)
- `/make_market` - Start placing a limit order
- `/orders` - View, search, and manage your orders
- `/check_account` - View account information (balance, open orders, positions, proxy status)
- `/set_ref_code` - Set referral code (5 characters, one-time setup)
- `/set_proxy` - Update proxy server configuration (format: ip:port:login:password)
- `/help` - View comprehensive bot instructions (available in English, Russian, and Chinese)
- `/support` - Contact administrator with questions or issues (supports text and photos)

### Admin Commands
- `/get_db` - Export user database and log files (admin only)
- `/get_invites [count]` - Get unused invite codes with statistics (default: 10, admin only)
- `/stats` - View comprehensive database statistics (admin only)
- `/delete_user` - Delete a user from the database (admin only)

## Automatic Order Synchronization

The bot automatically synchronizes your orders every 60 seconds:

### How it works:
1. **Status Check**: For each OPEN order, checks status via API
   - If order is FILLED: updates database to 'FILLED', sends notification with order details (price, market link)
   - If order is CANCELLED/EXPIRED/INVALIDATED: updates database accordingly, skips processing silently (no notification)
   - If status check fails: continues with normal processing (graceful degradation)

2. **Price Monitoring**: Monitors market prices and maintains a constant offset (in ticks) between the current market price and your order's target price

3. **Smart Updates**: Only moves orders when the price change exceeds the reposition threshold (default 0.5 cents)

4. **Batch Operations**: Efficiently cancels and places orders in batches per user

5. **Notifications**: You'll receive notifications when:
   - Market price changes and orders need to be moved (before repositioning)
   - Orders are successfully updated with new prices (after repositioning)
   - Orders are filled (with order details and market link)
   - Placement errors occur (with detailed error messages)

### Features:
- **Efficiency**: Skips repositioning when change < threshold (saves API calls and gas fees)
- **Reliability**: Only places new orders after successfully canceling old ones
- **Safety**: Validates all operations via API response codes (errno == 0)
- **User Awareness**: Detailed notifications for all important events
- **Performance**: Logs execution time for each user's processing

## Dependencies

- `aiogram==3.23.0` - Telegram Bot API framework
- `aiogram-dialog==2.4.0` - Dialog system for complex interactions
- `aiosqlite==0.22.0` - Async SQLite driver for non-blocking database operations
- `predict-sdk==0.0.8` - predict.fun SDK for market interactions (on-chain operations, order signing)
- `cryptography==46.0.3` - AES-GCM encryption
- `pydantic==2.12.5` - Settings management
- `pydantic-settings==2.12.0` - Environment variable settings
- `python-dotenv==1.2.1` - Environment variable loading
- `eth-account==0.13.7` - Ethereum account management
- `requests==2.32.5` - HTTP client for REST API
- `httpx==0.28.1` - Async HTTP client for proxy checking
- `pytest==9.0.2` - Testing framework
- `pytest-asyncio==1.3.0` - Async test support for pytest

## Technical Details

### Async Architecture
- All database operations use `aiosqlite` for true async I/O
- API calls are wrapped in `asyncio.to_thread()` to prevent blocking
- Background tasks run independently without blocking the main event loop
- Uses `PredictAPIClient` (REST API) and `predict_sdk.OrderBuilder` (SDK) for all API operations

### Order Synchronization Algorithm
1. Retrieves all users from the database
2. For each user:
   - Gets active orders from the database
   - For each order:
     - **Status Check**: Checks order status via API
       - If filled: updates DB, sends notification, skips processing
       - If cancelled: updates DB, skips processing
     - Fetches current market price (best_bid for BUY, best_ask for SELL)
     - Calculates new target price using saved `offset_ticks`
     - Calculates price change in cents
     - If price change ≥ `reposition_threshold_cents`, adds to cancellation/placement lists
     - Sends price change notification (only if order will be repositioned)
   - Cancels old orders in batch (validates via errno == 0)
   - Places new orders in batch (only if all old orders were cancelled)
   - Updates database with new order parameters (only for successful placements)
   - Sends order update notification (for successful placements)
   - Sends error notification (for failed placements)

### Invite System
- Invites are stored in `invites` table with fields: id, invite (unique), telegram_id, created_at, used_at
- Invite codes are 10-character alphanumeric strings
- Invites are validated before registration and used atomically at the end
- Admin can generate invites via `/get_invites` command
- System automatically creates new invites if needed

### Database Schema
- **users**: Encrypted user credentials (wallet, private key, API key)
  - `telegram_id` (PRIMARY KEY): User's Telegram ID
  - All sensitive data encrypted with AES-GCM
  - Unique constraints on wallet address, private key, and API key
  - `proxy_str`: Optional proxy configuration (ip:port:login:password)
  - `proxy_status`: Proxy health status (working/failed/unknown)
- **orders**: Order information (order_hash, order_api_id, market_slug, prices, amounts, status, etc.)
  - Status values: `OPEN`, `FILLED`, `CANCELLED`, `EXPIRED`, `INVALIDATED` (aligned with API terminology)
  - Default status: `OPEN`
  - Migration function updates old statuses automatically
- **invites**: Invite codes and usage tracking

## Testing

The project includes a test suite using pytest:

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_predict_api_client.py

# Run with verbose output
pytest -v
```

Test files are located in the `tests/` directory:
- `test_predict_api_client.py` - Tests for REST API client
- `test_sdk_operations.py` - Tests for SDK operations
- `test_sync_orders.py` - Tests for order synchronization

## Deployment

### Docker Deployment

See [DEPLOY.md](DEPLOY.md) for detailed deployment instructions using the provided `deploy.sh` script.

The deployment script supports:
- Full deployment (`./deploy.sh deploy`)
- View logs (`./deploy.sh logs`)
- Check status (`./deploy.sh status`)
- Stop container (`./deploy.sh stop`)
- Restart container (`./deploy.sh restart`)

### Manual Deployment

1. Ensure all dependencies are installed
2. Set up `.env` file with required variables
3. Create `logs/` directory for log files
4. Run the bot: `cd bot && python main.py`

## Disclaimer

This bot is provided as-is for educational and personal use. Always ensure you understand the risks involved in trading on prediction markets. The developers are not responsible for any financial losses.

## Support

For issues, questions, or contributions, please open an issue on GitHub.
