---
permalink: /
title: "***Making pixels dance and GPUs scream for a living.***"
author_profile: true
redirect_from: 
  - /about/
  - /about.html
---

***Fan Tang*** is an Associate Professor at the Institute of Computing Technology, Chinese Academy of Sciences (**ICT, CAS**), where he has been conducting research on image and video generation technology since 2022. Prior to joining ICT-CAS, he was a faculty member at the School of Artificial Intelligence, Jilin University. 

He received his Ph.D. in 2019 from the National Laboratory of Pattern Recognition (**NLPR**) at the Institute of Automation, CAS (**CASIA**), within the Multimedia Computing Group, under the supervision of Prof. [Baogang Hu](https://scholar.google.com/citations?user=Npo7kokAAAAJ&hl=en) and Prof. [Weiming Dong](https://scholar.google.com/citations?user=WKGx4k8AAAAJ&hl=en). During his doctoral studies, he spent one year as a visiting researcher at the University of Konstanz, Germany, collaborating with Prof. [Oliver Deussen](https://www.cgmi.uni-konstanz.de/personen/prof-dr-oliver-deussen/). 

His current research primarily focuses on ***2D digital humans***, ***image editing***, and ***digital art generation***.

## 🔥 News

{% include base_path %}
{% assign all_pubs = site.publications | sort: "date" | reverse %}
{% assign count = 0 %}
<ul style="list-style-type: none; padding-left: 0; margin-top: 0.5em; margin-bottom: 0.5em; font-size: 0.9em;">
{% for post in all_pubs %}
  {% assign venue_lower = post.venue | downcase %}
  {% unless venue_lower contains "arxiv" %}
    {% if count < 5 %}
      {% assign citation_clean = post.citation | split: '&quot;' | first %}
      {% assign authors_raw = citation_clean | strip %}
      {% assign first_author = authors_raw | split: ',' | first | strip %}
      {% assign venue_lower_check = post.venue | downcase %}
      {% assign is_conference = false %}
      {% if venue_lower_check contains "proceedings" or venue_lower_check contains "conference" %}
        {% assign is_conference = true %}
      {% endif %}
      {% assign venue_display = post.venue %}
      {% if venue_display contains "In the proceedings of " %}
        {% assign venue_display = venue_display | remove_first: "In the proceedings of " %}
      {% endif %}
      <li style="margin-bottom: 0.3em; line-height: 1.4;">
        <strong>🎉 "{{ post.title }}"</strong>
        {% if is_conference %}
          was published in <em>{{ venue_display }}</em>
        {% else %}
          was accepted by <em>{{ venue_display }}</em>
        {% endif %}
        ({{ post.date | date: "%Y" }}).
        <strong>Congratulations to {{ first_author }}!</strong>
      </li>
      {% assign count = count | plus: 1 %}
    {% endif %}
  {% endunless %}
{% endfor %}
</ul>




## 🎨 Representative Works

### 👤 2D Digital Human

![2D Digital Human](/images/representative-works/2d-digital-human.jpg)

<!-- Content will be added here -->

### 🖼️ Image Editing

![Image Editing](/images/representative-works/image-editing.jpg)

<!-- Content will be added here -->

### 🎭 Digital Arts

![Digital Arts](/images/representative-works/digital-arts.jpg)

<!-- Content will be added here -->

## 📢 Join Us
I am always looking for highly motivated students or interns who are interested in 2D AIGC.
- 🎯 **Research Directions**: We focus on the intersection of computer vision and computer graphics, powered by modern agents.
- 💻 **Required Skills**: A solid foundation in mathematics (linear algebra/optimization), proficiency in Python and PyTorch for deep learning research, and a strong capability for reading and writing top-tier academic papers in English.
- ⭐ **Desired Traits**: We value candidates who are highly self-motivated and intellectually curious, possessing the grit and persistence required to navigate the long-term challenges of high-level academic research.
- 📧 **How to Apply**: Please send your CV, transcripts, and representative research works to tfan.108@gmail.com with an email subject formatted as "Your Name - University".

