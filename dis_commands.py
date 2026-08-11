import discord
from discord.ext import commands

# Enable privileged intents
intents = discord.Intents.default()
intents.typing = True
intents.message_content = True  # Enable Message Content intent
intents.members = True

# Discord bot setup
bot = commands.Bot(command_prefix="!", intents=intents)

# test command to check if the bot is responsive
@bot.command(name='ping')
async def ping(ctx):
    await ctx.send('Pong!')

@bot.command(name='channel_info')
async def channel_info(ctx, channel_id: int):
    # Get the channel data from the channel ID
    try:
        channel = await bot.fetch_channel(channel_id)
    except discord.errors.NotFound:
        await ctx.send(f"Channel with ID {channel_id} not found.")
        return

    embed = discord.Embed(title=f"Channel Info for {channel.name}", color=0x00ff00)
    embed.add_field(name="Channel ID", value=channel.id, inline=False)
    embed.add_field(name="Channel Type", value=channel.type, inline=False)
    embed.add_field(name="Channel Guild", value=channel.guild.name, inline=False)
    embed.add_field(name="Channel Position", value=channel.position, inline=False)
    embed.add_field(name="Channel Topic", value=channel.topic or "None", inline=False)
    await ctx.send(embed=embed)

@bot.command(name='get_members')
async def get_members(ctx):
    # Use the enabled intents to get information about guild members
    guild = ctx.guild
    members = []
    async for member in guild.fetch_members():
        members.append(member)
    member_names = [member.name for member in members]
    embed = discord.Embed(title=f'Members in this guild: {", ".join(member_names)}', color=0xff0000)
    # await ctx.send(f'Members in this guild: {", ".join(member_names)}')
    await ctx.send(embed=embed)

@bot.command(name='check_attachments')
async def check_attachments(ctx):
    channel = ctx.channel
    attachments_info = []
    async for message in channel.history(limit=100):  # Adjust the limit as needed
        for attachment in message.attachments:
            attachments_info.append({
                "filename": attachment.filename,
                "url": attachment.url,
                "size": attachment.size,
                "author": message.author.name
            })
    if not attachments_info:
        await ctx.send("No attachments found in this channel.")
        return
    embed = discord.Embed(title=f"Attachments in {channel.name}", color=0x00ff00)
    for attachment in attachments_info:
        embed.add_field(
            name=f"Filename: {attachment['filename']}",
            value=f"URL: [Link]({attachment['url']})\nSize: {attachment['size']} bytes\nUploaded by: {attachment['author']}",
            inline=False
        )
    await ctx.send(embed=embed)

@bot.command(name='delete_file')
async def delete_file(ctx, *, filename: str):
    """Delete a file or folder from the current channel by name.
    Usage: !delete_file <filename or folder_name>
    """
    channel = ctx.channel
    
    if not filename:
        await ctx.send("Please provide a filename to delete.")
        return
    
    root_name = filename.rstrip('/').split('/')[0]
    root_base = __import__('os').path.splitext(root_name)[0]
    
    # Try both metadata filename patterns
    possible_metadata_names = [
        f"{root_base}_metadata.json",  # Single file without extension
        f"{root_name}_metadata.json"   # Folder with original name
    ]
    
    messages_to_delete = []
    filenames_to_delete = set()
    metadata_message = None
    
    try:
        # First pass: Find metadata and extract all chunk filenames
        async for message in channel.history(limit=2000):
            for attachment in message.attachments:
                if attachment.filename in possible_metadata_names:
                    metadata_message = message
                    try:
                        content = await attachment.read()
                        try:
                            import json
                            metadata = json.loads(content)
                        except:
                            from utils.util import cipher
                            metadata = json.loads(cipher.decrypt(content))
                        
                        # Extract chunks based on type
                        if metadata.get("upload_type") == "folder":
                            def extract_chunks(tree):
                                chunks = []
                                for name, item in tree.items():
                                    if item.get("type") == "file":
                                        chunks.extend(item.get("chunks", []))
                                    elif item.get("type") == "directory":
                                        chunks.extend(extract_chunks(item.get("children", {})))
                                return chunks
                            filenames_to_delete.update(extract_chunks(metadata.get("tree", {})))
                        else:
                            filenames_to_delete.update(metadata.get("chunks", []))
                    except Exception as e:
                        await ctx.send(f"Error parsing metadata: {e}")
                        return
            
            # Early exit once metadata is found
            if metadata_message:
                break
        
        if not metadata_message:
            await ctx.send(f"File or folder '{filename}' not found in this channel.")
            return
        
        messages_to_delete.append(metadata_message)
        
        # Second pass: Find all chunk messages
        async for message in channel.history(limit=2000):
            for attachment in message.attachments:
                if attachment.filename in filenames_to_delete:
                    messages_to_delete.append(message)
        
        # Delete messages
        delete_count = 0
        for message in messages_to_delete:
            try:
                await message.delete()
                delete_count += 1
            except discord.errors.NotFound:
                pass
            except Exception as e:
                await ctx.send(f"Error deleting message: {e}")
                return
        
        embed = discord.Embed(
            title="✅ Delete Complete",
            description=f"Successfully deleted **{filename}** and {delete_count} associated messages.",
            color=0x00ff00
        )
        await ctx.send(embed=embed)
    
    except Exception as e:
        embed = discord.Embed(
            title="❌ Delete Failed",
            description=f"Error: {str(e)}",
            color=0xff0000
        )
        await ctx.send(embed=embed)
