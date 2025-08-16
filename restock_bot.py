import os
import discord
from discord.ext import commands, tasks
import aiohttp
import asyncio
import json
from datetime import datetime
import logging

class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors and better formatting"""
    
    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
        'RESET': '\033[0m'      # Reset
    }
    
    def format(self, record):
        # Add color to level name
        level_color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        record.levelname = f"{level_color}{record.levelname:<8}{self.COLORS['RESET']}"
        
        # Format timestamp
        timestamp = datetime.fromtimestamp(record.created).strftime('%H:%M:%S')
        
        # Custom formatting for bot messages
        if record.name == '__main__':
            if 'Parsed' in record.getMessage():
                # Enhanced parsed messages with store counts
                msg = record.getMessage()
                if ': 0 available out of 0 locations' in msg:
                    sku = msg.split(':')[0].split()[-1]
                    return f"[{timestamp}] 📦 {sku} - 0/0 stores (preorder)"
                elif ': 0 available out of' in msg:
                    sku = msg.split(':')[0].split()[-1]
                    total_stores = msg.split('out of')[1].split('locations')[0].strip()
                    return f"[{timestamp}] ❌ {sku} - 0/{total_stores} stores"
                elif 'available out of' in msg:
                    sku = msg.split(':')[0].split()[-1]
                    available = msg.split(':')[1].split('available')[0].strip()
                    total_stores = msg.split('out of')[1].split('locations')[0].strip()
                    return f"[{timestamp}] ✅ {sku} - {available}/{total_stores} stores"
                else:
                    return f"[{timestamp}] {level_color}BOT{self.COLORS['RESET']} {record.getMessage()}"
            elif 'Restock alert sent' in record.getMessage():
                # Extract product name and store count from alert message
                msg = record.getMessage()
                if 'for' in msg and '(' in msg:
                    product_info = msg.split('for')[1].split('(')[0].strip()
                    if '-' in msg and 'stores' in msg:
                        store_count = msg.split('-')[1].split('stores')[0].strip()
                        return f"[{timestamp}] 🚨 ALERT: {product_info} ({store_count} stores)"
                    else:
                        return f"[{timestamp}] 🚨 ALERT: {product_info}"
                else:
                    return f"[{timestamp}] 🚨 {msg}"
            else:
                return f"[{timestamp}] {level_color}BOT{self.COLORS['RESET']} {record.getMessage()}"
        
        # Default formatting for other loggers
        return f"[{timestamp}] {record.levelname} {record.getMessage()}"

# Set up enhanced logging
def setup_logging():
    # Create formatter
    formatter = ColoredFormatter()
    
    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    
    # Reduce Discord.py noise
    logging.getLogger('discord').setLevel(logging.WARNING)
    logging.getLogger('discord.client').setLevel(logging.WARNING)
    logging.getLogger('discord.gateway').setLevel(logging.WARNING)
    
    return logging.getLogger(__name__)

# Initialize logging
logger = setup_logging()

# Bot configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHANNEL_ID = int(os.getenv('CHANNEL_ID'))
USER_ID = os.getenv('USER_ID')
CHECK_INTERVAL = 1800  # Check every 30 min (in seconds)

# Add error checking
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")
if not CHANNEL_ID:
    raise ValueError("CHANNEL_ID environment variable is required")
if not USER_ID:
    raise ValueError("USER_ID environment variable is required")


# Load products from JSON file
try:
    with open('products.json', 'r') as f:
        PRODUCTS_TO_MONITOR = json.load(f)
    
    # Log priority breakdown
    priority_counts = {}
    for product in PRODUCTS_TO_MONITOR:
        priority = product.get('priority', 'unknown')
        priority_counts[priority] = priority_counts.get(priority, 0) + 1
    
    logger.info(f"Loaded {len(PRODUCTS_TO_MONITOR)} products from products.json")
    logger.info(f"Priority breakdown: {priority_counts}")
    
except FileNotFoundError:
    logger.error("products.json file not found!")
    PRODUCTS_TO_MONITOR = []
except json.JSONDecodeError as e:
    logger.error(f"Error parsing products.json: {e}")
    PRODUCTS_TO_MONITOR = []

class RestockBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        
        self.session = None
        self.last_stock_status = {}
        
    async def setup_hook(self):
        """Initialize the HTTP session and start monitoring"""
        self.session = aiohttp.ClientSession()
        self.monitor_restocks.start()
        logger.info("Restock monitoring started")
    
    async def close(self):
        """Clean up resources"""
        if self.session:
            await self.session.close()
        await super().close()

    async def check_product_availability(self, sku, zip_code):
        """
        Check if a product is available at Best Buy locations near the zip code
        """
        try:
            # Snormax API endpoint for Best Buy stock checking
            url = f"https://api.snormax.com/stock/bestbuy"
            
            # Headers to mimic a real browser request
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://www.snormax.com/',
                'Origin': 'https://www.snormax.com'
            }
            
            # Parameters for the API call
            params = {
                'sku': sku,
                'zip': zip_code
            }
            
            async with self.session.get(url, headers=headers, params=params, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    return self.parse_stock_response(data, sku)
                elif response.status == 404:
                    logger.warning(f"Product {sku} not found")
                    return {'available': False, 'error': 'Product not found'}
                else:
                    logger.error(f"HTTP {response.status} error when checking {sku}")
                    return None
                    
        except asyncio.TimeoutError:
            logger.error(f"Timeout when checking {sku}")
            return None
        except Exception as e:
            logger.error(f"Error checking availability for {sku}: {e}")
            return None
    
    def parse_stock_response(self, data, sku):
        """
        Parse the Snormax API response for Best Buy stock status
        Based on actual API response format with 'items' array containing stock data
        """
        try:
            if isinstance(data, dict) and 'items' in data and len(data['items']) > 0:
                item = data['items'][0]  # Get the first (and usually only) item
                
                if 'locations' not in item:
                    logger.warning(f"No location data found for {sku}")
                    return None
                
                available_locations = []
                total_locations = len(item['locations'])
                
                # Check each location for stock availability
                for location_data in item['locations']:
                    location_id = location_data.get('locationId')
                    
                    # Check if location has availability data
                    if 'availability' in location_data:
                        availability = location_data['availability']
                        pickup_quantity = availability.get('availablePickupQuantity', 0)
                        
                        # Check if there's stock available for pickup
                        if pickup_quantity and pickup_quantity > 0:
                            available_locations.append({
                                'locationId': location_id,
                                'pickupQuantity': pickup_quantity,
                                'fulfillmentType': availability.get('fulfillmentType', 'PICKUP')
                            })
                    
                    # Also check in-store availability
                    if 'inStoreAvailability' in location_data:
                        in_store = location_data['inStoreAvailability']
                        in_store_quantity = in_store.get('availableInStoreQuantity', 0)
                        
                        # If we already found pickup availability, update it; otherwise create new entry
                        existing_location = next((loc for loc in available_locations if loc['locationId'] == location_id), None)
                        if existing_location:
                            existing_location['inStoreQuantity'] = in_store_quantity
                        elif in_store_quantity and in_store_quantity > 0:
                            available_locations.append({
                                'locationId': location_id,
                                'inStoreQuantity': in_store_quantity,
                                'fulfillmentType': 'IN_STORE'
                            })
                
                # Get location names from the main locations array
                location_names = {}
                if 'locations' in data:
                    for loc in data['locations']:
                        location_names[loc['id']] = f"{loc.get('name', 'Unknown')} - {loc.get('city', 'Unknown')}"
                
                # Add location names to available locations
                for loc in available_locations:
                    loc['name'] = location_names.get(loc['locationId'], f"Location {loc['locationId']}")
                
                # Create response object
                result = {
                    'available': len(available_locations) > 0,
                    'stores': available_locations,
                    'total_stores': total_locations,
                    'locations_checked': [location_names.get(loc_data.get('locationId'), f"Location {loc_data.get('locationId')}") 
                                        for loc_data in item['locations']],
                    'last_checked': datetime.now().isoformat()
                }
                
                # Log for debugging
                logger.info(f"Parsed {sku}: {len(available_locations)} available out of {total_locations} locations")
                if available_locations:
                    logger.info(f"Available at: {[loc['name'] for loc in available_locations[:3]]}...")  # Show first 3
                
                return result
                
            else:
                # Log the response format for debugging
                logger.info(f"No items found in response for {sku}. Response keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
                return None
            
        except Exception as e:
            logger.error(f"Error parsing stock response for {sku}: {e}")
            return None
    
    @tasks.loop(seconds=CHECK_INTERVAL)
    async def monitor_restocks(self):
        """Main monitoring loop"""
        try:
            channel = self.get_channel(CHANNEL_ID)
            if not channel:
                logger.error(f"Could not find channel with ID {CHANNEL_ID}")
                return
            
            for product in PRODUCTS_TO_MONITOR:
                sku = product['sku']
                zip_code = product['zip_code']
                name = product.get('name', sku)
                
                # Check current stock status
                current_status = await self.check_product_availability(sku, zip_code)
                
                if current_status is None:
                    continue
                
                # Get previous status
                previous_status = self.last_stock_status.get(sku, {})
                
                # Check if stock status changed from unavailable to available
                if (current_status['available'] and 
                    not previous_status.get('available', False)):
                    
                    # Get product priority for enhanced alerts
                    priority = next((p.get('priority', 'medium') for p in PRODUCTS_TO_MONITOR if p['sku'] == sku), 'medium')
                    category = next((p.get('category', 'Unknown') for p in PRODUCTS_TO_MONITOR if p['sku'] == sku), 'Unknown')
                    set_name = next((p.get('set', 'Unknown') for p in PRODUCTS_TO_MONITOR if p['sku'] == sku), 'Unknown')

                    # Priority-based alert styling
                    if priority == 'top':
                        title = "🚨🔥 TOP PRIORITY RESTOCK! 🔥🚨"
                        color = 0xff0000  # Red
                    elif priority == 'high':
                        title = "🎉 HIGH PRIORITY RESTOCK! 🎉"
                        color = 0xff8800  # Orange
                    elif priority == 'medium':
                        title = "📦 RESTOCK ALERT! 📦"
                        color = 0x00ff00  # Green
                    else:  # low
                        title = "📝 Restock Alert"
                        color = 0x808080  # Gray

                    # Send restock notification
                    embed = discord.Embed(
                        title=title,
                        description=f"**{name}** is back in stock!",
                        color=color,
                        timestamp=datetime.now()
                    )
                    embed.add_field(name="SKU", value=sku, inline=True)
                    embed.add_field(name="Zip Code", value=zip_code, inline=True)
                    embed.add_field(name="Priority", value=priority.upper(), inline=True)
                    embed.add_field(name="Category", value=category, inline=True)
                    embed.add_field(name="Set", value=set_name, inline=True)
                    
                    # Add store information if available
                    if current_status.get('stores'):
                        store_count = len(current_status['stores'])
                        embed.add_field(name="Stores with Stock", value=f"{store_count} stores", inline=True)
                        
                        # Add list of store locations (limit to first 10 to avoid Discord message limits)
                        store_list = []
                        for i, store in enumerate(current_status['stores'][:10]):
                            store_name = store.get('name', f"Location {store.get('locationId', 'Unknown')}")
                            pickup_qty = store.get('pickupQuantity', '')
                            in_store_qty = store.get('inStoreQuantity', '')
                            
                            # Format quantity display
                            qty_info = []
                            if pickup_qty:
                                if pickup_qty == 9999:
                                    qty_info.append("3+")
                                else:
                                    qty_info.append(str(pickup_qty))
                            if in_store_qty and in_store_qty != pickup_qty:
                                if in_store_qty == 9999:
                                    qty_info.append("3+ in-store")
                                else:
                                    qty_info.append(f"{in_store_qty} in-store")
                            
                            qty_display = f" ({', '.join(qty_info)})" if qty_info else ""
                            store_list.append(f"• {store_name}{qty_display}")
                        
                        # Add remaining store count if there are more than 10
                        if store_count > 10:
                            store_list.append(f"• ... and {store_count - 10} more stores")
                        
                        store_text = "\n".join(store_list)
                        embed.add_field(name="Available Locations", value=store_text, inline=False)
                    
                    embed.add_field(name="Link", value=f"[Snormax](https://www.snormax.com/lookup/bestbuy/{sku}?title=&image=&zipcode={zip_code})", inline=False)
                    
                    await channel.send(f"<@{USER_ID}>", embed=embed)
                    logger.info(f"Restock alert sent for {name} ({sku}) - {len(current_status.get('stores', []))} stores")
                
                # Update stored status
                self.last_stock_status[sku] = current_status
                
        except Exception as e:
            logger.error(f"Error in monitoring loop: {e}")
    
    @monitor_restocks.before_loop
    async def before_monitor_restocks(self):
        """Wait until the bot is ready before starting monitoring"""
        await self.wait_until_ready()

# Bot commands
bot = RestockBot()

@bot.event
async def on_ready():
    logger.info(f'{bot.user} has connected to Discord!')
    logger.info(f'Monitoring {len(PRODUCTS_TO_MONITOR)} products')

@bot.command(name='status')
async def check_status(ctx, priority_filter: str = None):
    """Check current status of monitored products with optional priority filter
    Usage: !status [top|high|medium|low]
    """
    if not bot.last_stock_status:
        await ctx.send("No products have been checked yet. Please wait for the first check cycle.")
        return
    
    # Validate priority filter
    valid_priorities = ['top', 'high', 'medium', 'low']
    if priority_filter and priority_filter.lower() not in valid_priorities:
        await ctx.send(f"Invalid priority filter. Use one of: {', '.join(valid_priorities)}")
        return
    
    # Group products by priority and filter by availability
    available_products = []
    unavailable_products = []
    
    for product in PRODUCTS_TO_MONITOR:
        sku = product['sku']
        name = product.get('name', sku)
        priority = product.get('priority', 'medium')
        status = bot.last_stock_status.get(sku, {})
        
        # Apply priority filter if specified
        if priority_filter and priority.lower() != priority_filter.lower():
            continue
        
        product_info = {
            'name': name,
            'sku': sku,
            'priority': priority,
            'status': status,
            'zip_code': product.get('zip_code', '90503')
        }
        
        if status and status.get('available'):
            available_products.append(product_info)
        else:
            unavailable_products.append(product_info)
    
    # Create embeds
    embeds = []
    
    # Helper function to create status embed
    def create_status_embed(products, title, color):
        if not products:
            return None
            
        embed = discord.Embed(
            title=title,
            color=color,
            timestamp=datetime.now()
        )
        
        # Add products (max 10 per embed to avoid Discord limits with detailed store info)
        for i, product in enumerate(products[:10]):
            status = product['status']
            snormax_link = f"[snormax](https://www.snormax.com/lookup/bestbuy/{product['sku']}?title=&image=&zipcode={product['zip_code']})"
            
            if status and status.get('available'):
                # Format store information like in restock alerts
                store_count = len(status.get('stores', []))
                
                # Create the field value with store details
                field_value = f"**Priority:** {product['priority'].upper()}\n"
                field_value += f"**SKU:** {product['sku']}\n"
                field_value += f"**Stores with Stock:** {store_count} stores\n"
                
                # Add detailed store information
                if status.get('stores'):
                    store_list = []
                    for j, store in enumerate(status['stores'][:8]):  # Limit to 8 stores to avoid field length issues
                        store_name = store.get('name', f"Location {store.get('locationId', 'Unknown')}")
                        pickup_qty = store.get('pickupQuantity', '')
                        in_store_qty = store.get('inStoreQuantity', '')
                        
                        # Format quantity display (same logic as restock alerts)
                        qty_info = []
                        if pickup_qty:
                            if pickup_qty == 9999:
                                qty_info.append("3+")
                            else:
                                qty_info.append(str(pickup_qty))
                        if in_store_qty and in_store_qty != pickup_qty:
                            if in_store_qty == 9999:
                                qty_info.append("3+ in-store")
                            else:
                                qty_info.append(f"{in_store_qty} in-store")
                        
                        qty_display = f" ({', '.join(qty_info)})" if qty_info else ""
                        store_list.append(f"• {store_name}{qty_display}")
                    
                    # Add remaining store count if there are more than 8
                    if store_count > 8:
                        store_list.append(f"• ... and {store_count - 8} more stores")
                    
                    field_value += f"**Available Locations:**\n" + "\n".join(store_list) + f"\n"
                
                field_value += f"**Link:** {snormax_link}"
                
            else:
                # For out of stock items
                total_stores = status.get('total_stores', 'Unknown') if status else 'Unknown'
                field_value = f"**Priority:** {product['priority'].upper()}\n"
                field_value += f"**SKU:** {product['sku']}\n"
                field_value += f"**Status:** Out of Stock\n"
                if status:
                    field_value += f"**Total Stores Checked:** {total_stores}\n"
                field_value += f"**Link:** {snormax_link}"
            
            embed.add_field(
                name=product['name'],
                value=field_value,
                inline=False  # Changed to False for better readability with store lists
            )
        
        # Add overflow notice if there are more than 10
        if len(products) > 10:
            embed.add_field(
                name="⚠️ More Products",
                value=f"... and {len(products) - 10} more products. Use priority filters to see specific items.",
                inline=False
            )
        
        return embed
    
    # Create embeds for available and unavailable products
    if available_products:
        available_embed = create_status_embed(
            available_products, 
            f"✅ Available Products ({len(available_products)})",
            0x00ff00
        )
        if available_embed:
            embeds.append(available_embed)
    
    if unavailable_products:
        unavailable_embed = create_status_embed(
            unavailable_products,
            f"❌ Out of Stock Products ({len(unavailable_products)})",
            0xff0000
        )
        if unavailable_embed:
            embeds.append(unavailable_embed)
    
    # Send embeds
    if embeds:
        for embed in embeds:
            await ctx.send(embed=embed)
    else:
        if priority_filter:
            await ctx.send(f"No {priority_filter} priority products found or checked yet.")
        else:
            await ctx.send("No products found.")

@bot.command(name='add')
async def add_product(ctx, sku: str, zip_code: str, *, name: str = None):
    """Add a new product to monitor"""
    new_product = {
        'sku': sku,
        'zip_code': zip_code,
        'name': name or sku
    }
    
    # Check if product already exists
    for product in PRODUCTS_TO_MONITOR:
        if product['sku'] == sku and product['zip_code'] == zip_code:
            await ctx.send(f"Product {sku} at {zip_code} is already being monitored.")
            return
    
    PRODUCTS_TO_MONITOR.append(new_product)
    await ctx.send(f"Added {name or sku} (SKU: {sku}) at {zip_code} to monitoring list.")
    logger.info(f"Added new product to monitor: {sku} at {zip_code}")

@bot.command(name='remove')
async def remove_product(ctx, sku: str, zip_code: str):
    """Remove a product from monitoring"""
    for i, product in enumerate(PRODUCTS_TO_MONITOR):
        if product['sku'] == sku and product['zip_code'] == zip_code:
            removed_product = PRODUCTS_TO_MONITOR.pop(i)
            if sku in bot.last_stock_status:
                del bot.last_stock_status[sku]
            await ctx.send(f"Removed {removed_product.get('name', sku)} from monitoring list.")
            logger.info(f"Removed product from monitoring: {sku} at {zip_code}")
            return
    
    await ctx.send(f"Product {sku} at {zip_code} not found in monitoring list.")

@bot.command(name='debug')
async def debug_product(ctx, sku: str, zip_code: str):
    """Debug command to see raw API response"""
    try:
        # Check current stock status
        current_status = await bot.check_product_availability(sku, zip_code)
        
        if current_status:
            embed = discord.Embed(
                title="Debug Information",
                color=0xff9900,
                timestamp=datetime.now()
            )
            embed.add_field(name="SKU", value=sku, inline=True)
            embed.add_field(name="Zip Code", value=zip_code, inline=True)
            embed.add_field(name="Available", value=current_status['available'], inline=True)
            embed.add_field(name="Total Stores", value=current_status.get('total_stores', 'Unknown'), inline=True)
            embed.add_field(name="Stores with Stock", value=len(current_status.get('stores', [])), inline=True)
            
            if current_status.get('locations_checked'):
                locations_text = "\n".join(current_status['locations_checked'][:5])  # Show first 5
                if len(current_status['locations_checked']) > 5:
                    locations_text += f"\n... and {len(current_status['locations_checked']) - 5} more"
                embed.add_field(name="Locations Checked", value=locations_text, inline=False)
            
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"Could not retrieve data for SKU {sku} at {zip_code}")
            
    except Exception as e:
        await ctx.send(f"Error debugging {sku}: {str(e)}")
        logger.error(f"Debug command error: {e}")

@bot.command(name='commands')
async def commands_list(ctx):
    """Show available commands"""
    embed = discord.Embed(
        title="Bot Commands",
        color=0x0099ff
    )
    embed.add_field(name="!status [priority]", value="Check stock status (optional: top, high, medium, low)", inline=False)
    embed.add_field(name="!add [sku] [zipcode] [name]", value="Add a product to monitor", inline=False)
    embed.add_field(name="!remove [sku] [zipcode]", value="Remove a product from monitoring", inline=False)
    embed.add_field(name="!list [priority]", value="Simple list: Product Name - SKU format", inline=False)
    embed.add_field(name="!listd [priority]", value="Detailed list with Set/Category info (also: !listdetailed)", inline=False)
    embed.add_field(name="!debug [sku] [zipcode]", value="Debug API response for a specific product", inline=False)
    embed.add_field(name="!commands", value="Show this help message", inline=False)
    
    await ctx.send(embed=embed)
    
@bot.command(name='list')
async def list_products(ctx, priority_filter: str = None):
    """List all monitored products in simple format
    Usage: !list [top|high|medium|low]
    """
    if not PRODUCTS_TO_MONITOR:
        await ctx.send("No products are currently being monitored.")
        return
    
    # Validate priority filter
    valid_priorities = ['top', 'high', 'medium', 'low']
    if priority_filter and priority_filter.lower() not in valid_priorities:
        await ctx.send(f"Invalid priority filter. Use one of: {', '.join(valid_priorities)}")
        return
    
    # Group products by priority
    priority_groups = {
        'top': [],
        'high': [],
        'medium': [],
        'low': []
    }
    
    for product in PRODUCTS_TO_MONITOR:
        priority = product.get('priority', 'medium')
        if priority in priority_groups:
            priority_groups[priority].append(product)
    
    # Determine which priorities to show
    if priority_filter:
        priorities_to_show = [priority_filter.lower()]
    else:
        priorities_to_show = ['top', 'high', 'medium', 'low']
    
    # Create simple text-based lists
    message_parts = []
    
    priority_emojis = {'top': '🔥', 'high': '🚨', 'medium': '⚠️', 'low': '📝'}
    
    for priority in priorities_to_show:
        products = priority_groups[priority]
        if not products:
            if priority_filter:
                await ctx.send(f"No {priority} priority products found.")
                return
            continue
        
        message_parts.append(f"\n**{priority_emojis.get(priority, '📦')} {priority.upper()} Priority ({len(products)}):**")
        
        for product in products:
            name = product.get('name', product['sku'])
            sku = product['sku']
            message_parts.append(f"• {name} - {sku}")
    
    # Combine all parts
    if not message_parts:
        await ctx.send("No products found.")
        return
    
    # Add header
    if priority_filter:
        full_message = f"**📦 {priority_filter.upper()} Priority Products:**" + "\n".join(message_parts)
    else:
        full_message = f"**📦 Monitoring {len(PRODUCTS_TO_MONITOR)} Products:**" + "\n".join(message_parts)
    
    # Split message if too long (Discord has 2000 character limit)
    if len(full_message) <= 2000:
        await ctx.send(full_message)
    else:
        # Split into chunks
        chunks = []
        current_chunk = ""
        
        for part in message_parts:
            if len(current_chunk + part + "\n") <= 1950:  # Leave some buffer
                current_chunk += part + "\n"
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = part + "\n"
        
        if current_chunk:
            chunks.append(current_chunk)
        
        # Add header to first chunk
        if chunks:
            if priority_filter:
                chunks[0] = f"**📦 {priority_filter.upper()} Priority Products:**\n" + chunks[0]
            else:
                chunks[0] = f"**📦 Monitoring {len(PRODUCTS_TO_MONITOR)} Products:**\n" + chunks[0]
        
        for i, chunk in enumerate(chunks):
            if i > 0:
                chunk = f"**📦 Continued ({i+1}/{len(chunks)}):**\n" + chunk
            await ctx.send(chunk)

@bot.command(name='listd')
async def list_products_detailed(ctx, priority_filter: str = None):
    """List all monitored products with detailed information (aliases: listdetailed)
    Usage: !listd [top|high|medium|low]
    """
    if not PRODUCTS_TO_MONITOR:
        await ctx.send("No products are currently being monitored.")
        return
    
    # Validate priority filter
    valid_priorities = ['top', 'high', 'medium', 'low']
    if priority_filter and priority_filter.lower() not in valid_priorities:
        await ctx.send(f"Invalid priority filter. Use one of: {', '.join(valid_priorities)}")
        return
    
    # Group products by priority
    priority_groups = {
        'top': [],
        'high': [],
        'medium': [],
        'low': []
    }
    
    for product in PRODUCTS_TO_MONITOR:
        priority = product.get('priority', 'medium')
        if priority in priority_groups:
            priority_groups[priority].append(product)
    
    # Determine which priorities to show
    if priority_filter:
        priorities_to_show = [priority_filter.lower()]
    else:
        priorities_to_show = ['top', 'high', 'medium', 'low']
    
    # Create embeds
    embeds = []
    
    for priority in priorities_to_show:
        products = priority_groups[priority]
        if not products:
            if priority_filter:
                await ctx.send(f"No {priority} priority products found.")
                return
            continue
            
        # Emoji mapping for priorities
        priority_emojis = {
            'top': '🔥',
            'high': '🚨', 
            'medium': '⚠️',
            'low': '📝'
        }
        
        embed = discord.Embed(
            title=f"{priority_emojis.get(priority, '📦')} {priority.upper()} Priority Products ({len(products)})",
            color={
                'top': 0xff0000,      # Red
                'high': 0xff8800,     # Orange  
                'medium': 0x00ff00,   # Green
                'low': 0x808080       # Gray
            }.get(priority, 0x0099ff),
            timestamp=datetime.now()
        )
        
        # Handle pagination for large lists
        products_per_embed = 25
        total_pages = (len(products) + products_per_embed - 1) // products_per_embed
        
        for page in range(total_pages):
            if page > 0:  # Create new embed for additional pages
                embed = discord.Embed(
                    title=f"{priority_emojis.get(priority, '📦')} {priority.upper()} Priority Products (Page {page + 1}/{total_pages})",
                    color={
                        'top': 0xff0000,
                        'high': 0xff8800,
                        'medium': 0x00ff00,
                        'low': 0x808080
                    }.get(priority, 0x0099ff),
                    timestamp=datetime.now()
                )
            
            start_idx = page * products_per_embed
            end_idx = min(start_idx + products_per_embed, len(products))
            
            for product in products[start_idx:end_idx]:
                # Create Snormax link
                sku = product['sku']
                zip_code = product['zip_code']
                snormax_link = f"[snormax](https://www.snormax.com/lookup/bestbuy/{sku}?title=&image=&zipcode={zip_code})"
                
                embed.add_field(
                    name=product.get('name', product['sku']),
                    value=f"SKU: {product['sku']}\nSet: {product.get('set', 'Unknown')}\nCategory: {product.get('category', 'Unknown')}\nLink: {snormax_link}",
                    inline=True
                )
            
            embeds.append(embed)
    
    # Send all embeds
    if embeds:
        for embed in embeds:
            await ctx.send(embed=embed)
    else:
        await ctx.send("No products found.")

if __name__ == '__main__':
    # Run the bot
    bot.run(BOT_TOKEN)