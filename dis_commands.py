import discord
from discord.ext import commands

# Enable privileged intents
intents = discord.Intents.default()
intents.typing = True
intents.message_content = True  # Enable Message Content intent
intents.members = True

# Discord bot setup
bot = commands.Bot(command_prefix="/", intents=intents)

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

@bot.command(name='ping')
async def ping(ctx):
    await ctx.send('Pong!')