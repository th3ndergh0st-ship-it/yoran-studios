import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from config import PRIMARY, SUCCESS, ERROR, INFO, WARNING
import economy_data as econ

TRIVIA_COOLDOWN = 300  # coins are involved, so trivia can't be spammed

TIPS = [
    "Use `TweenService` instead of manually changing properties every frame — it's smoother and cheaper on performance.",
    "Organize your game with folders inside `ServerScriptService`, `ReplicatedStorage`, and `StarterPlayerScripts` — don't dump everything in one place.",
    "Never trust the client. Validate everything important (damage, currency, inventory) on the server.",
    "Use `RemoteEvents` for client → server actions and `RemoteFunctions` sparingly — they can yield and cause exploitable delays.",
    "`table.insert`/`table.remove` are O(1) at the end of an array but O(n) at the start — keep that in mind for big lists.",
    "Use `CollectionService` tags instead of checking `Name` or `ClassName` to group similar objects.",
    "Cache `WaitForChild` results in a variable instead of calling it every time you need the same instance.",
    "Use `task.wait()` instead of the older `wait()` — it's more accurate and has less overhead.",
    "Test your game with the Roblox Studio 'Server' + 'Client' simulation to catch replication bugs before publishing.",
    "Keep your UI responsive: use `UIListLayout` and `UIGridLayout` instead of hand-placing every frame.",
    "Use `Attributes` for small pieces of data on instances instead of creating extra `Value` objects.",
    "Profile your game with the Microprofiler (Ctrl+F6) before optimizing blindly.",
    "Debounce your triggers! A `Touched` event can fire multiple times per second from a single body part.",
    "Use `pcall` around anything that can fail (DataStore calls, HTTP requests) so one error doesn't crash a script.",
    "Group related RemoteEvents under one folder and name them clearly — future you will thank you.",
    "Avoid infinite `while true do ... end` loops without a `task.wait()` — they can freeze the game or hit throttling.",
    "Use `DataStoreService:GetAsync` with retries and `pcall`, and always have a backup plan if the request fails.",
    "Keep parts `Anchored` when they don't need physics — it saves a surprising amount of performance.",
]

TRIVIA = [
    {
        "question": "Which service is used to safely save player data between sessions?",
        "options": ["DataStoreService", "TweenService", "PathfindingService", "CollectionService"],
        "answer": 0,
    },
    {
        "question": "What keyword declares a variable that can't be reassigned in Luau?",
        "options": ["const", "final", "there's no such keyword in Luau", "readonly"],
        "answer": 2,
    },
    {
        "question": "Which event fires when a player joins the game?",
        "options": ["Players.PlayerAdded", "Players.PlayerJoined", "Game.OnPlayerJoin", "Workspace.PlayerAdded"],
        "answer": 0,
    },
    {
        "question": "What should you use instead of `wait()` for better accuracy in modern scripts?",
        "options": ["delay()", "task.wait()", "spawn()", "sleep()"],
        "answer": 1,
    },
    {
        "question": "Where should code run that must NOT be visible/editable by exploiters?",
        "options": ["LocalScript in StarterGui", "Script in ServerScriptService", "ModuleScript in ReplicatedStorage", "LocalScript in StarterPlayerScripts"],
        "answer": 1,
    },
    {
        "question": "Which object type lets you share code between server and client scripts?",
        "options": ["Script", "LocalScript", "ModuleScript", "RemoteScript"],
        "answer": 2,
    },
    {
        "question": "What does 'debounce' commonly prevent in Roblox scripts?",
        "options": ["Memory leaks", "An event firing multiple times in quick succession", "Server lag", "Data loss"],
        "answer": 1,
    },
]

BUTTON_LABELS = ["A", "B", "C", "D"]


class TriviaView(discord.ui.View):
    def __init__(self, author_id: int, question: dict):
        super().__init__(timeout=30)
        self.author_id = author_id
        self.question = question
        self.message: discord.Message | None = None
        self.answered = False
        for i, option in enumerate(question["options"]):
            self.add_item(TriviaButton(i, option))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ This isn't your trivia question — run `/trivia` yourself!", color=ERROR),
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self):
        if self.answered or self.message is None:
            return
        for item in self.children:
            item.disabled = True
            if isinstance(item, TriviaButton) and item.index == self.question["answer"]:
                item.style = discord.ButtonStyle.success
        embed = self.message.embeds[0]
        embed.color = ERROR
        embed.add_field(name="Result", value="⌛ Time's up! The correct answer is highlighted.", inline=False)
        try:
            await self.message.edit(embed=embed, view=self)
        except discord.HTTPException:
            pass


class TriviaButton(discord.ui.Button):
    def __init__(self, index: int, label: str):
        super().__init__(label=f"{BUTTON_LABELS[index]}. {label}"[:80], style=discord.ButtonStyle.secondary)
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        view: TriviaView = self.view
        view.answered = True
        correct = self.index == view.question["answer"]

        for item in view.children:
            item.disabled = True
            if isinstance(item, TriviaButton) and item.index == view.question["answer"]:
                item.style = discord.ButtonStyle.success
            elif item is self and not correct:
                item.style = discord.ButtonStyle.danger

        if correct:
            reward = random.randint(10, 25)
            new_bal = econ.add_balance(interaction.guild.id, interaction.user.id, reward)
            desc = f"✅ Correct! You earned {econ.CURRENCY_EMOJI} `{reward}` {econ.CURRENCY_NAME}.\nBalance: {econ.CURRENCY_EMOJI} `{new_bal:,}`"
            color = SUCCESS
        else:
            correct_text = view.question["options"][view.question["answer"]]
            desc = f"❌ Not quite — the correct answer was **{correct_text}**."
            color = ERROR

        embed = interaction.message.embeds[0]
        embed.color = color
        embed.set_field_at(0, name="Result", value=desc, inline=False) if embed.fields else embed.add_field(name="Result", value=desc, inline=False)
        await interaction.response.edit_message(embed=embed, view=view)


class Education(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="tip", description="Get a random Roblox development tip")
    async def tip(self, interaction: discord.Interaction):
        text = random.choice(TIPS)
        embed = discord.Embed(title="💡  Dev Tip", description=text, color=INFO)
        embed.set_footer(text="Yoran Studios  •  Dev Tips")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="trivia", description="Answer a Roblox/Lua trivia question for coins")
    async def trivia(self, interaction: discord.Interaction):
        last = econ.get_cooldown(interaction.guild.id, interaction.user.id, "last_trivia")
        remaining = TRIVIA_COOLDOWN - (time.time() - last)
        if remaining > 0:
            m, s = divmod(int(remaining), 60)
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"⏰ One trivia at a time! Try again in **{m}m {s}s**.", color=WARNING),
                ephemeral=True,
            )
        econ.set_cooldown(interaction.guild.id, interaction.user.id, "last_trivia", time.time())
        question = random.choice(TRIVIA)
        embed = discord.Embed(title="🧠  Trivia Time!", description=question["question"], color=PRIMARY)
        embed.set_footer(text="You have 30 seconds to answer — correct answers earn coins!")
        view = TriviaView(interaction.user.id, question)
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot):
    await bot.add_cog(Education(bot))
