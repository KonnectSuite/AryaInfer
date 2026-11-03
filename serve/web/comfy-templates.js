// The picture presets the Images room offers: a title, a prompt to start from, and whether it wants a text or an edit
// workflow.  They are prompts, not graphs - the workflow stays whatever the user picked, and the prompt is editable.
window.COMFY_TEMPLATES = [
  {id: "portrait", title: "Studio portrait", tag: "People", role: "text",
   prompt: "A studio portrait of a person with soft window light from the left, neutral grey backdrop, 85 mm lens, " +
           "shallow depth of field, natural skin texture, calm expression"},
  {id: "product-white", title: "Product on white", tag: "Product", role: "text",
   prompt: "A single bottle of amber glass on a seamless white background, soft studio light, a gentle reflection " +
           "under it, catalogue product photography, sharp focus"},
  {id: "product-set", title: "Product in a set", tag: "Product", role: "text",
   prompt: "A ceramic coffee cup on a marble counter with a linen cloth, morning light through a window, steam " +
           "rising, muted warm palette, editorial product photo"},
  {id: "icon", title: "App icon", tag: "Graphic", role: "text",
   prompt: "A flat app icon of a paper plane, bold simple shapes, rounded square tile, deep blue gradient " +
           "background, one accent colour, clean vector look, centred"},
  {id: "logo", title: "Logo mark", tag: "Graphic", role: "text",
   prompt: "A minimal geometric logo mark of a mountain and a wave, two colours, flat vector, generous negative " +
           "space, on a plain background, no text"},
  {id: "sticker", title: "Die-cut sticker", tag: "Graphic", role: "text",
   prompt: "A cheerful die-cut sticker of a smiling red fox head, thick white border, soft flat colours, slight " +
           "drop shadow, on a plain white background"},
  {id: "landscape", title: "Cinematic landscape", tag: "Scenes", role: "text",
   prompt: "A still mountain lake at dawn, low mist over the water, first light on the ridge, reflections, " +
           "cinematic wide shot, natural colour grade"},
  {id: "isometric", title: "Isometric room", tag: "Scenes", role: "text",
   prompt: "An isometric view of a cosy study: a wooden desk, a warm lamp, bookshelves, a plant, soft clay render, " +
           "pastel palette, clean background, no people"},
  {id: "food", title: "Food photo", tag: "Scenes", role: "text",
   prompt: "A rustic bowl of tomato soup with a swirl of cream and basil leaves, dark wooden table, overhead " +
           "natural light, steam, moody food photography"},
  {id: "poster", title: "Film poster", tag: "Graphic", role: "text",
   prompt: "A minimalist film poster: a lone figure on a dune under a huge sun, two-colour print, deep orange and " +
           "navy, grainy paper texture, large empty sky for a title, no text"},
  {id: "watercolour", title: "Watercolour a picture", tag: "Edit", role: "edit",
   prompt: "Repaint this picture as a loose watercolour: wet edges, visible paper grain, a limited palette of " +
           "three or four colours, keep the composition"},
  {id: "cutout", title: "Cut the background away", tag: "Edit", role: "edit",
   prompt: "Remove the background completely and keep only the main subject, clean edges, keep the subject's " +
           "colours and lighting unchanged"},
];
