var builder = WebApplication.CreateBuilder(args);

var app = builder.Build();

// Redirect ads.txt to Ezoic's managed ads.txt
app.MapGet("/ads.txt", () => Results.Redirect("https://srv.adstxtmanager.com/19390/clujpug.ro", permanent: true));

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