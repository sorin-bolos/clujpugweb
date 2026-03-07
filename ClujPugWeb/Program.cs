var builder = WebApplication.CreateBuilder(args);

var app = builder.Build();

// Serve privacy policy at clean URL
app.MapGet("/privacy-policy", async context =>
{
    context.Response.ContentType = "text/html; charset=utf-8";
    await context.Response.SendFileAsync(Path.Combine(app.Environment.WebRootPath, "privacy-policy.html"));
});

// Configure the HTTP request pipeline
if (!app.Environment.IsDevelopment())
{
    app.UseExceptionHandler("/Home/Error");
    app.UseHsts();
    app.UseHttpsRedirection();
}

// Set Index.html as the default file
app.UseDefaultFiles(new DefaultFilesOptions
{
    DefaultFileNames = { "Index.html" }
});

// Enable static file serving
app.UseStaticFiles();

app.Run();